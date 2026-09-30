"""
LLM 网关 (统一 LLM 调用出口)
==============================

职责:
- 多 profile 路由: agent(主对话) / rag(生成) / intent(分类) / condense(改写)
- 熔断分桶: 各 profile 独立熔断, 互不影响
- 分级降级: 主模型失败 → 备用模型 → 固定文案
- 成本计量: 每次 LLM 调用记录 token/延迟, 双写指标

所有 LLM 构造从这里出, 消除 graph.py / rag_query.py / voice_agent 三处硬编码。
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional

from loguru import logger

from .resilience import CircuitOpenError, LLMCircuitBreaker


DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class LLMProfile:
    """LLM 配置 profile"""
    name: str
    model: str
    temperature: float = 0.3
    streaming: bool = False
    fallback_model: Optional[str] = None
    description: str = ""


# ──────────────────────────────────────────────
# 默认 profiles (可被环境变量覆盖)
# ──────────────────────────────────────────────

def _build_profiles() -> Dict[str, LLMProfile]:
    return {
        "agent": LLMProfile(
            name="agent",
            model=os.getenv("ASSISTANT_MODEL", "qwen3.7-plus"),
            temperature=0.3,
            streaming=False,
            fallback_model=os.getenv("ASSISTANT_MODEL_FALLBACK", "qwen-turbo"),
            description="主对话 Agent (带工具, 非流式决策)",
        ),
        "rag": LLMProfile(
            name="rag",
            model=os.getenv("RAG_MODEL", "qwen3.7-plus"),
            temperature=0.0,
            streaming=True,
            description="RAG 知识问答生成 (流式)",
        ),
        "chitchat": LLMProfile(
            name="chitchat",
            model=os.getenv("CHITCHAT_MODEL", "qwen3.7-plus"),
            temperature=0.5,
            streaming=True,
            description="闲聊 (流式)",
        ),
        "intent": LLMProfile(
            name="intent",
            model=os.getenv("INTENT_MODEL", "qwen-turbo"),
            temperature=0.0,
            streaming=False,
            description="意图分类 (廉价小模型)",
        ),
        "condense": LLMProfile(
            name="condense",
            model=os.getenv("CONDENSE_MODEL", "qwen-turbo"),
            temperature=0.0,
            streaming=False,
            description="查询改写 (廉价小模型)",
        ),
    }


# ──────────────────────────────────────────────
# 调用计量
# ──────────────────────────────────────────────

@dataclass
class LLMUsage:
    profile: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    success: bool = True
    fallback_used: bool = False


# ──────────────────────────────────────────────
# 网关
# ──────────────────────────────────────────────

class LLMGateway:
    """所有 LLM 调用的唯一出口"""

    def __init__(self):
        self._profiles = _build_profiles()
        self._breakers: Dict[str, LLMCircuitBreaker] = {}
        self._lc = None
        self._usages: list[LLMUsage] = []  # 指标桩 (生产接 Prometheus)
        self._metrics = None

    def _init_metrics(self):
        if self._metrics is None:
            from ..core.metrics import get_metrics
            self._metrics = get_metrics()
        return self._metrics

    def _init_lc(self):
        if self._lc:
            return self._lc
        from langchain_openai import ChatOpenAI
        self._lc = {"ChatOpenAI": ChatOpenAI}
        return self._lc

    def _get_breaker(self, profile_name: str) -> LLMCircuitBreaker:
        if profile_name not in self._breakers:
            self._breakers[profile_name] = LLMCircuitBreaker(
                name=f"llm-{profile_name}",
                failure_threshold=0.6,
                min_calls=4,
                recovery_timeout=30.0,
            )
        return self._breakers[profile_name]

    def get(self, profile: str) -> Any:
        """获取指定 profile 的 LLM 实例 (带熔断保护, 无工具绑定)"""
        ChatOpenAI = self._init_lc()["ChatOpenAI"]
        p = self._profiles.get(profile)
        if p is None:
            raise ValueError(f"unknown LLM profile: {profile}")

        # Langfuse 钩子: 配置后自动全链路 trace, 未配置零开销
        from ..core.metrics import get_langfuse_handler
        handler = get_langfuse_handler()
        callbacks = [handler] if handler else None

        return ChatOpenAI(
            model=p.model,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=DASHSCOPE_BASE_URL,
            temperature=p.temperature,
            streaming=p.streaming,
            callbacks=callbacks,
        )

    def get_with_tools(self, profile: str, tool_schemas: list) -> Any:
        """获取绑定工具的 LLM (用于 Function Calling)"""
        llm = self.get(profile)
        return llm.bind_tools(tool_schemas)

    async def ainvoke(self, profile: str, messages, **kw) -> Any:
        """同步式 LLM 调用 (带熔断 + 分级降级)"""
        p = self._profiles[profile]
        breaker = self._get_breaker(profile)
        t0 = time.time()
        usage = LLMUsage(profile=profile, model=p.model)

        # 主模型
        try:
            llm = self.get(profile)
            result = await breaker.call(llm.ainvoke, messages, **kw)
            usage.latency_ms = int((time.time() - t0) * 1000)
            self._record_usage(usage)
            return result
        except CircuitOpenError:
            # 熔断 → 尝试备用模型
            if p.fallback_model and p.fallback_model != p.model:
                logger.warning(f"[{profile}] circuit open, trying fallback: {p.fallback_model}")
                return await self._invoke_fallback(profile, p, messages, usage, t0, **kw)
            raise

    async def ainvoke_with_tools(self, profile: str, tool_schemas: list, messages, **kw) -> Any:
        """带工具绑定的 LLM 调用 (Function Calling, 带熔断 + 分级降级)

        与 ainvoke 的区别: 先 bind_tools 再走 breaker, 失败时备用模型也带工具绑定。
        """
        p = self._profiles[profile]
        breaker = self._get_breaker(profile)
        t0 = time.time()
        usage = LLMUsage(profile=profile, model=p.model)

        # 主模型 (带工具)
        try:
            llm = self.get_with_tools(profile, tool_schemas)
            result = await breaker.call(llm.ainvoke, messages, **kw)
            usage.latency_ms = int((time.time() - t0) * 1000)
            self._record_usage(usage)
            return result
        except CircuitOpenError:
            # 熔断 → 尝试备用模型 (同样带工具绑定)
            if p.fallback_model and p.fallback_model != p.model:
                logger.warning(f"[{profile}] circuit open, trying fallback with tools: {p.fallback_model}")
                return await self._invoke_fallback_with_tools(profile, p, tool_schemas, messages, usage, t0, **kw)
            raise

    async def _invoke_fallback(self, profile, p, messages, usage, t0, **kw) -> Any:
        ChatOpenAI = self._init_lc()["ChatOpenAI"]
        try:
            fallback_llm = ChatOpenAI(
                model=p.fallback_model,
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url=DASHSCOPE_BASE_URL,
                temperature=p.temperature,
                streaming=p.streaming,
            )
            result = await fallback_llm.ainvoke(messages, **kw)
            usage.model = p.fallback_model
            usage.fallback_used = True
            usage.latency_ms = int((time.time() - t0) * 1000)
            self._record_usage(usage)
            return result
        except Exception as e:
            usage.success = False
            usage.latency_ms = int((time.time() - t0) * 1000)
            self._record_usage(usage)
            raise

    async def _invoke_fallback_with_tools(self, profile, p, tool_schemas, messages, usage, t0, **kw) -> Any:
        ChatOpenAI = self._init_lc()["ChatOpenAI"]
        try:
            fallback_llm = ChatOpenAI(
                model=p.fallback_model,
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url=DASHSCOPE_BASE_URL,
                temperature=p.temperature,
                streaming=p.streaming,
            ).bind_tools(tool_schemas)
            result = await fallback_llm.ainvoke(messages, **kw)
            usage.model = p.fallback_model
            usage.fallback_used = True
            usage.latency_ms = int((time.time() - t0) * 1000)
            self._record_usage(usage)
            return result
        except Exception as e:
            usage.success = False
            usage.latency_ms = int((time.time() - t0) * 1000)
            self._record_usage(usage)
            raise

    async def astream(self, profile: str, messages, **kw) -> AsyncIterator[Any]:
        """流式 LLM 调用 (带熔断保护)"""
        breaker = self._get_breaker(profile)
        llm = self.get(profile)
        t0 = time.time()
        usage = LLMUsage(profile=profile, model=self._profiles[profile].model)

        try:
            async for chunk in breaker.call_stream(llm.astream, messages, **kw):
                yield chunk
            usage.latency_ms = int((time.time() - t0) * 1000)
            self._record_usage(usage)
        except CircuitOpenError:
            usage.success = False
            usage.latency_ms = int((time.time() - t0) * 1000)
            self._record_usage(usage)
            raise

    def _record_usage(self, usage: LLMUsage) -> None:
        self._usages.append(usage)
        m = self._init_metrics()
        labels = {"profile": usage.profile, "model": usage.model}
        m.inc("llm_requests_total", labels)
        m.inc("llm_requests_failed_total", labels, value=0 if usage.success else 1)
        m.inc("llm_fallback_total", labels, value=1 if usage.fallback_used else 0)
        m.observe("llm_latency_ms", usage.latency_ms, labels)
        # 生产环境: 推送 token 用量 (llm_gateway 从 resp.usage_metadata 提取后落在这里)
        logger.debug(
            f"llm usage: {usage.profile}/{usage.model} "
            f"latency={usage.latency_ms}ms ok={usage.success} fb={usage.fallback_used}"
        )

    def breaker_snapshots(self) -> Dict[str, Dict[str, Any]]:
        """暴露熔断器状态 (给指标面板)"""
        return {name: b.snapshot() for name, b in self._breakers.items()}


# 进程级单例
_gateway: Optional[LLMGateway] = None


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
