"""
语音管线可观测性: 监控埋点 + 结构化日志
=====================================

三层可观测性:
1. Prometheus 指标 (通过 core/metrics.py 最小实现)
   - 请求级: QPS / 延迟 / 成功率 / 错误率
   - 管线级: ASR 识别延迟 / TTS 合成延迟 / 端到端延迟
   - 资源级: 活跃会话数 / 并发处理数
2. 结构化日志 (loguru, JSON 格式)
   - 每个管线阶段记录 request_id / user_id / 耗时 / 结果
   - 错误带完整 traceback
3. Langfuse Trace (env 开关, 已有基础设施)
   - ASR → Agent → TTS 全链路串联, 按 request_id 查询

埋点原则:
- 所有埋点用 contextvars 传递 request_id / user_id, 不侵入函数签名
- 错误降级: 指标记录失败不影响主流程
- 延迟观测: 用 observe() 存 latest + sum, 生产换 prometheus_client.Histogram
"""

import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from loguru import logger

from ..core.metrics import get_metrics


# ──────────────────────────────────────────────
# 语音管线上下文 (跨异步调用传递)
# ──────────────────────────────────────────────

@dataclass
class VoiceTraceContext:
    """一次语音/文字请求的追踪上下文"""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: int = 0
    thread_id: str = ""
    mode: str = ""          # "text" | "voice"
    t_start: float = field(default_factory=time.time)

    # 管线阶段时间戳
    t_asr_start: float = 0.0
    t_asr_end: float = 0.0
    t_agent_start: float = 0.0
    t_agent_end: float = 0.0
    t_tts_start: float = 0.0
    t_tts_end: float = 0.0

    # 统计
    asr_chunks: int = 0
    asr_final_text: str = ""
    agent_tool_calls: int = 0
    tts_audio_bytes: int = 0
    intent: str = ""
    route: str = ""
    error: str = ""


_voice_ctx: ContextVar[Optional[VoiceTraceContext]] = ContextVar(
    "voice_trace_ctx", default=None
)


def set_voice_trace_context(ctx: VoiceTraceContext) -> Token:
    return _voice_ctx.set(ctx)


def reset_voice_trace_context(token: Token) -> None:
    _voice_ctx.reset(token)


def get_voice_trace() -> Optional[VoiceTraceContext]:
    return _voice_ctx.get()


# ──────────────────────────────────────────────
# Prometheus 指标定义
# ──────────────────────────────────────────────

def _metrics():
    return get_metrics()


def record_connection(user_id: int) -> None:
    """连接建立"""
    _metrics().inc("voice_connections_total", {"user_id": str(user_id)})
    _metrics().inc("voice_active_connections", value=1)
    logger.info(f"[voice] connection established user_id={user_id}")


def record_disconnect(user_id: int, reason: str) -> None:
    """连接断开"""
    _metrics().inc("voice_active_connections", value=-1)
    _metrics().inc("voice_disconnects_total", {"reason": reason})
    logger.info(f"[voice] disconnected user_id={user_id} reason={reason}")


def record_query_start(mode: str) -> None:
    """请求开始 (文字/语音)"""
    _metrics().inc("voice_queries_total", {"mode": mode})
    _metrics().inc("voice_active_queries", value=1)
    ctx = get_voice_trace()
    if ctx:
        ctx.mode = mode
        logger.info(
            f"[voice] query_start request_id={ctx.request_id} "
            f"user_id={ctx.user_id} mode={mode}"
        )


def record_query_end(status: str = "ok") -> None:
    """请求完成"""
    _metrics().inc("voice_active_queries", value=-1)
    ctx = get_voice_trace()
    if ctx:
        latency_ms = int((time.time() - ctx.t_start) * 1000)
        _metrics().observe("voice_e2e_latency_ms", latency_ms, {"mode": ctx.mode, "status": status})
        _metrics().inc("voice_query_status_total", {"mode": ctx.mode, "status": status})

        logger.info(
            f"[voice] query_done request_id={ctx.request_id} "
            f"user_id={ctx.user_id} mode={ctx.mode} status={status} "
            f"latency={latency_ms}ms intent={ctx.intent} route={ctx.route} "
            f"asr_chunks={ctx.asr_chunks} tool_calls={ctx.agent_tool_calls} "
            f"tts_bytes={ctx.tts_audio_bytes}"
        )


def record_asr_start() -> None:
    """ASR 开始"""
    ctx = get_voice_trace()
    if ctx:
        ctx.t_asr_start = time.time()
        logger.debug(f"[voice] asr_start request_id={ctx.request_id}")


def record_asr_chunk() -> None:
    """ASR 部分识别"""
    _metrics().inc("voice_asr_chunks_total")
    ctx = get_voice_trace()
    if ctx:
        ctx.asr_chunks += 1


def record_asr_final(text: str) -> None:
    """ASR 句尾定稿"""
    ctx = get_voice_trace()
    if ctx:
        ctx.t_asr_end = time.time()
        ctx.asr_final_text = text
        latency_ms = int((ctx.t_asr_end - ctx.t_asr_start) * 1000) if ctx.t_asr_start else 0
        _metrics().observe("voice_asr_latency_ms", latency_ms)
        logger.info(
            f"[voice] asr_final request_id={ctx.request_id} "
            f"latency={latency_ms}ms text_len={len(text)} text={text[:100]}"
        )


def record_agent_start() -> None:
    """Agent 图执行开始"""
    ctx = get_voice_trace()
    if ctx:
        ctx.t_agent_start = time.time()
        logger.debug(f"[voice] agent_start request_id={ctx.request_id}")


def record_agent_end(intent: str = "", route: str = "", tool_calls: int = 0) -> None:
    """Agent 图执行完成"""
    ctx = get_voice_trace()
    if ctx:
        ctx.t_agent_end = time.time()
        ctx.intent = intent
        ctx.route = route
        ctx.agent_tool_calls = tool_calls
        latency_ms = int((ctx.t_agent_end - ctx.t_agent_start) * 1000) if ctx.t_agent_start else 0
        _metrics().observe("voice_agent_latency_ms", latency_ms, {"intent": intent or "unknown"})
        logger.info(
            f"[voice] agent_done request_id={ctx.request_id} "
            f"latency={latency_ms}ms intent={intent} route={route} "
            f"tool_calls={tool_calls}"
        )


def record_tts_start() -> None:
    """TTS 合成开始"""
    ctx = get_voice_trace()
    if ctx:
        ctx.t_tts_start = time.time()
        logger.debug(f"[voice] tts_start request_id={ctx.request_id}")


def record_tts_chunk(audio_bytes: int) -> None:
    """TTS 音频帧输出"""
    ctx = get_voice_trace()
    if ctx:
        ctx.tts_audio_bytes += audio_bytes
    _metrics().inc("voice_tts_chunks_total")


def record_tts_end() -> None:
    """TTS 合成完成"""
    ctx = get_voice_trace()
    if ctx:
        ctx.t_tts_end = time.time()
        latency_ms = int((ctx.t_tts_end - ctx.t_tts_start) * 1000) if ctx.t_tts_start else 0
        _metrics().observe("voice_tts_latency_ms", latency_ms)
        logger.info(
            f"[voice] tts_done request_id={ctx.request_id} "
            f"latency={latency_ms}ms audio_bytes={ctx.tts_audio_bytes}"
        )


def record_hitl_pending(confirm_id: str) -> None:
    """HITL 挂起"""
    _metrics().inc("voice_hitl_pending_total")
    ctx = get_voice_trace()
    if ctx:
        logger.info(
            f"[voice] hitl_pending request_id={ctx.request_id} "
            f"confirm_id={confirm_id} mode={ctx.mode}"
        )


def record_hitl_resolved(action: str) -> None:
    """HITL 确认/拒绝"""
    _metrics().inc("voice_hitl_resolved_total", {"action": action})
    logger.info(f"[voice] hitl_resolved action={action}")


def record_error(stage: str, error: str) -> None:
    """管线错误"""
    _metrics().inc("voice_errors_total", {"stage": stage, "error": error[:50]})
    ctx = get_voice_trace()
    if ctx:
        ctx.error = error
        logger.error(
            f"[voice] error request_id={ctx.request_id} "
            f"user_id={ctx.user_id} stage={stage} error={error}"
        )
    else:
        logger.error(f"[voice] error stage={stage} error={error}")


def record_rate_limit(user_id: int) -> None:
    """限流触发"""
    _metrics().inc("voice_rate_limited_total", {"user_id": str(user_id)})
    logger.warning(f"[voice] rate_limited user_id={user_id}")


def record_idle_timeout(user_id: int) -> None:
    """空闲踢出"""
    _metrics().inc("voice_idle_timeout_total", {"user_id": str(user_id)})
    logger.warning(f"[voice] idle_timeout user_id={user_id}")
