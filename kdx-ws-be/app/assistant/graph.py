"""
Baby Assistant 完整 LangGraph 实现 (非伪代码，可直接运行)

落地 app/example 全部生产实践方案：

图结构:
                    ┌─────────────┐
     START ───────▶ │ entry_node  │  加载宝宝上下文 + 意图识别(两级: 规则→LLM)
                    └──────┬──────┘
                    route_after_intent (conditional_edges 动态路由)
           ┌───────────────┼──────────────────┐
           ▼               ▼                  ▼
     ┌──────────┐   ┌───────────┐     ┌───────────┐
     │  agent   │   │    rag    │     │  chitchat │
     │(ReAct循环)│   │(RAG检索生成)│    │ (流式闲聊) │
     └────┬─────┘   └─────┬─────┘     └─────┬─────┘
   route_after_agent      │                 │
    ┌──────┼─────────┐     │                 │
    ▼      ▼         ▼     ▼                 ▼
 ┌──────┐ ┌────┐ ┌────────┐
 │tools │ │wait│ │respond │   wait=HITL确认暂停 → END(由WS层恢复)
 └──┬───┘ └─┬──┘ └───┬────┘
    └──────▶│        │  tools 完成回到 agent 继续推理
            ▼        ▼
           END      END

生产实践对应:
- 意图识别: intent_node 两级策略(规则优先→LLM兜底, 置信度<0.6走fallback)
- 动态路由: route_after_intent 声明式路由表
- Function Calling: agent_node bind_tools + ReAct 循环
- 工具注册中心: registry.get_schemas_for_llm() 动态注入工具
- HITL: 写操作工具 → needs_confirmation → wait_confirm 出口暂停 → WS层收集确认 → resume 入口恢复
- 幂等: tool_exec_node 写操作幂等键去重
- 熔断降级: llm_breaker 包住 LLM 调用, 熔断时走模板降级
- 鉴权: user_id 由 WS 层 JWT 校验后注入, 工具层按 user_id 强制隔离
"""

import asyncio
import json
import os
import time
from datetime import date
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from loguru import logger

from .resilience import CircuitOpenError, LLMCircuitBreaker
from .tool_registry import ToolRegistry, build_default_registry

# ──────────────────────────────────────────────
# LangChain / LangGraph 懒加载 (与 rag_query.py 同模式，避免 import 期拉起 torch)
# ──────────────────────────────────────────────

_lc = {}


def _init_lc():
    if _lc:
        return _lc
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import (
        AIMessage, HumanMessage, SystemMessage, ToolMessage,
    )
    from langgraph.graph import StateGraph, START, END

    _lc.update({
        "ChatOpenAI": ChatOpenAI,
        "AIMessage": AIMessage,
        "HumanMessage": HumanMessage,
        "SystemMessage": SystemMessage,
        "ToolMessage": ToolMessage,
        "StateGraph": StateGraph,
        "START": START,
        "END": END,
    })
    return _lc


DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = os.getenv("ASSISTANT_MODEL", "qwen3.7-plus")
MAX_TOOL_ROUNDS = 5          # ReAct 最大循环轮数(防失控)
CONFIDENCE_THRESHOLD = 0.6   # 意图置信度阈值，低于走 fallback

# 模块级共享: 工具注册中心 + LLM 熔断器 (进程级单例)
_REGISTRY: Optional[ToolRegistry] = None
_LLM_BREAKER: Optional[LLMCircuitBreaker] = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_default_registry()
    return _REGISTRY


def get_llm_breaker() -> LLMCircuitBreaker:
    global _LLM_BREAKER
    if _LLM_BREAKER is None:
        _LLM_BREAKER = LLMCircuitBreaker(
            name="assistant-llm",
            failure_threshold=0.6,
            min_calls=4,
            recovery_timeout=30.0,
        )
    return _LLM_BREAKER


def _make_llm(streaming: bool = False, bind_tools_schemas: Optional[list] = None):
    ChatOpenAI = _init_lc()["ChatOpenAI"]
    llm = ChatOpenAI(
        model=MODEL_NAME,
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=DASHSCOPE_BASE_URL,
        temperature=0.3,
        streaming=streaming,
    )
    if bind_tools_schemas:
        return llm.bind_tools(bind_tools_schemas)
    return llm


# ──────────────────────────────────────────────
# State 定义 (LangGraph 状态机)
# ──────────────────────────────────────────────

class AssistantState(TypedDict, total=False):
    # 基础
    user_id: int
    query: str
    request_id: str
    resume: bool                       # HITL 恢复入口标记
    confirmed: bool                    # 用户已 approve

    # 会话
    messages: List[Any]                # langchain messages (含多轮历史)

    # 意图与路由
    intent: str                        # data_query / knowledge_qa / chitchat
    confidence: float
    slots: Dict[str, Any]
    route: str

    # 上下文
    baby_context: str                  # 宝宝信息 + 今日日期 (注入 system prompt)

    # 工具链路
    tool_rounds: int
    tool_calls: Optional[List[Dict[str, Any]]]  # agent 决策出的待执行工具调用
    tool_trace: List[Dict[str, Any]]   # 前端展示的工具调用轨迹
    pending_write: Optional[Dict[str, Any]]  # HITL: 待确认的写操作
    confirmed_call: Optional[Dict[str, Any]] # 恢复后待执行的工具调用

    # 输出
    answer: str
    sources: List[Dict[str, Any]]
    error: str


# ──────────────────────────────────────────────
# 意图识别: 规则优先 → LLM 兜底 (example/intent_recognition.py 落地)
# ──────────────────────────────────────────────

# 规则路由表: 意图 → 关键词 (命中即 data_query)
DATA_QUERY_PATTERNS = [
    ("milk", ["奶量", "喂奶", "喝奶", "吃奶", "奶 ", "毫升", "ml", "母乳", "奶粉", "记录奶"]),
    ("temperature", ["体温", "发烧", "低烧", "高烧", "发热", "度"]),
    ("sleep", ["睡眠", "睡觉", "入睡", "午睡", "小睡", "睡"]),
    ("diaper", ["尿不湿", "尿裤", "拉了", "尿了", "换尿", "便便", "大便", "粑粑"]),
    ("expense", ["花费", "花了", "消费", "开销", "买了", "支出", "记账", "多少钱"]),
    ("growth", ["身高", "体重", "头围", "成长", "长高", "长重"]),
    ("vaccine", ["疫苗", "接种", "打针", "接种证"]),
    ("birthday", ["生日", "周岁", "倒计时"]),
    ("baby_info", ["宝宝信息", "月龄", "多大"]),
]

KNOWLEDGE_PATTERNS = [
    ["辅食", "怎么添加", "什么时候可以", "能不能吃", "正常吗", "怎么办",
     "为什么", "如何", "应该", "建议", "黄疸", "湿疹", "呛奶", "肠绞痛", "补钙", "维生素d"],
]

CHITCHAT_PATTERNS = [
    ["你好", "你是谁", "谢谢", "嗨", "hello", "hi"],
]


def _rule_intent(query: str) -> Optional[Dict[str, Any]]:
    """第一级: 规则意图识别 (零延迟零成本，覆盖高频意图)"""
    q = query.lower()

    for _, keywords in DATA_QUERY_PATTERNS:
        for kw in keywords:
            if kw in q or kw in query:
                return {"intent": "data_query", "confidence": 0.9, "slots": {}}

    for kw in KNOWLEDGE_PATTERNS[0]:
        if kw in q or kw in query:
            return {"intent": "knowledge_qa", "confidence": 0.85, "slots": {}}

    for kw in CHITCHAT_PATTERNS[0]:
        if kw in q:
            return {"intent": "chitchat", "confidence": 0.8, "slots": {}}

    # 数字+单位模式 → 记录类写操作 (如 "记录喂奶80ml" "体温37.5")
    import re
    if re.search(r"(记录|记一下|添加|记)", query):
        return {"intent": "data_query", "confidence": 0.85, "slots": {}}
    if re.search(r"\d+(\.\d+)?\s*(ml|毫升|度|kg|公斤|厘米|cm)", q):
        return {"intent": "data_query", "confidence": 0.75, "slots": {}}

    return None


async def _llm_intent(query: str) -> Dict[str, Any]:
    """第二级: LLM few-shot 意图分类 (规则未命中时)"""
    prompt = (
        "你是意图分类器。对用户输入分类为以下三类之一，只输出JSON:\n"
        '- data_query: 查询/记录宝宝的奶量、体温、睡眠、尿不湿、花费、身高体重、疫苗、生日等数据\n'
        '- knowledge_qa: 育儿知识咨询(怎么/为什么/能不能等)\n'
        '- chitchat: 闲聊或其他\n\n'
        '示例:\n'
        '输入: 今天喝了多少奶 → {"intent":"data_query","confidence":0.95}\n'
        '输入: 6个月能吃鸡蛋吗 → {"intent":"knowledge_qa","confidence":0.92}\n'
        '输入: 记录喂奶80毫升 → {"intent":"data_query","confidence":0.95}\n'
        '输入: 讲个笑话 → {"intent":"chitchat","confidence":0.9}\n\n'
        f'输入: {query}\n输出:'
    )
    try:
        llm = _make_llm()
        resp = await llm.ainvoke([_init_lc()["HumanMessage"](content=prompt)])
        text = (resp.content or "").strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            return {
                "intent": parsed.get("intent", "chitchat"),
                "confidence": float(parsed.get("confidence", 0.5)),
                "slots": parsed.get("slots", {}),
            }
    except Exception as e:
        logger.warning(f"llm_intent failed: {e}")
    return {"intent": "knowledge_qa", "confidence": 0.55, "slots": {}}


# ──────────────────────────────────────────────
# 事件发送 (闭包注入 ws，与 rag_query.py 模式一致)
# ──────────────────────────────────────────────

async def _emit(ws, event_type: str, data: Dict[str, Any]):
    if ws is None:
        return
    try:
        await ws.send_json({"type": event_type, "data": data})
    except Exception:
        pass


# ──────────────────────────────────────────────
# 图节点实现
# ──────────────────────────────────────────────

def make_entry_node(ws, emit):
    """入口节点: HITL resume 直通 / 正常流程加载上下文+意图识别"""

    async def entry_node(state: AssistantState) -> Dict[str, Any]:
        # HITL 恢复: 跳过意图识别，直接进入 agent 继续执行已确认的写操作
        if state.get("resume") and state.get("confirmed_call"):
            return {"route": "data_query", "pending_write": None}

        query = state["query"]
        await emit("intent_start", {"query": query})

        # 加载宝宝上下文 (数据级鉴权: 仅查当前 user)
        baby_context = await _load_baby_context(state["user_id"])

        # 两级意图识别
        rule = _rule_intent(query)
        if rule:
            intent_res = rule
        else:
            intent_res = await _safe_llm_intent(query)

        intent = intent_res["intent"]
        confidence = intent_res["confidence"]
        if confidence < CONFIDENCE_THRESHOLD:
            intent = "chitchat"  # 低置信度兜底

        await emit("intent_detected", {
            "intent": intent,
            "confidence": round(confidence, 2),
            "source": "rule" if rule else "llm",
        })
        return {
            "intent": intent,
            "confidence": confidence,
            "slots": intent_res.get("slots", {}),
            "baby_context": baby_context,
        }

    return entry_node


async def _load_baby_context(user_id: int) -> str:
    from .repository import BabyDataRepository
    from ..core.database import SessionLocal
    try:
        repo = BabyDataRepository(SessionLocal())
        info = await asyncio.to_thread(repo.get_baby_info, user_id)
        today = date.today()
        if not info:
            return f"今天是 {today.isoformat()}。用户尚未添加宝宝信息。"
        birth = date.fromisoformat(info["birthday"])
        months = (today.year - birth.year) * 12 + today.month - birth.month
        if today.day < birth.day:
            months -= 1
        gender = {"M": "男宝", "F": "女宝"}.get(info.get("gender"), "宝宝")
        return (
            f"今天是 {today.isoformat()}。宝宝信息: 名字={info['name']}, {gender}, "
            f"生日={info['birthday']}, 月龄={max(months,0)}个月。"
        )
    except Exception as e:
        logger.warning(f"load_baby_context failed: {e}")
        return f"今天是 {date.today().isoformat()}。宝宝信息加载失败。"


async def _safe_llm_intent(query: str) -> Dict[str, Any]:
    try:
        return await get_llm_breaker().call(_llm_intent, query)
    except CircuitOpenError:
        # LLM 熔断 → 规则降级: 默认知识问答
        return {"intent": "knowledge_qa", "confidence": 0.55, "slots": {}}


def route_after_intent(state: AssistantState) -> Literal["agent", "rag", "chitchat", "fallback"]:
    """动态路由 (example/dynamic_routing.py 落地): 声明式 intent→node 映射"""
    route_map = {
        "data_query": "agent",
        "knowledge_qa": "rag",
        "chitchat": "chitchat",
    }
    return route_map.get(state.get("intent"), "fallback")


# ── 数据 Agent 节点 (Function Calling ReAct 循环) ──────────────

def make_agent_node(ws, emit):
    SystemMessage = _init_lc()["SystemMessage"]
    HumanMessage = _init_lc()["HumanMessage"]
    registry = get_registry()
    schemas = registry.get_schemas_for_llm()

    async def agent_node(state: AssistantState) -> Dict[str, Any]:
        query = state["query"]
        messages = list(state.get("messages") or [])

        # HITL 恢复: 执行已确认的写操作(由 tool_exec 直接执行, 这里透传标记)
        if state.get("resume") and state.get("confirmed_call"):
            return {"route": "data_query"}  # conditional edge 不经过 agent 主逻辑

        system = (
            "你是宝宝养育助手 Assistant。可以调用工具查询和记录宝宝数据。\n"
            f"{state.get('baby_context', '')}\n"
            "规则:\n"
            "1. 数据查询/记录必须调用对应工具，不要编造数据\n"
            "2. 用户想记录数据但缺少必要参数时，先追问补全再调用工具\n"
            "3. 拿到工具结果后，用简洁友好的中文总结给用户\n"
            "4. 一次只调用必要的工具\n"
        )
        # messages 只含历史轮次 (WS 层 history), 当前问题必须拼入对话末尾,
        # 否则 LLM 收不到用户消息 → 只能自我介绍, 更不会决策调用工具
        msgs = [SystemMessage(content=system)] + messages + [HumanMessage(content=query)]

        try:
            llm = _make_llm(streaming=False, bind_tools_schemas=schemas)
            resp = await get_llm_breaker().call(llm.ainvoke, msgs)
        except CircuitOpenError:
            return {"answer": "【系统降级】AI 服务暂时不可用，请稍后重试。", "route": "agent"}

        tool_calls = list(getattr(resp, "tool_calls", None) or [])

        # 无工具调用 → 直接回答
        if not tool_calls:
            answer = resp.content or "我在呢，请问想查询或记录什么数据？"
            await emit("generate_chunk", {"chunk": answer})
            await emit("answer_done", {"answer": answer, "tool_trace": state.get("tool_trace", [])})
            return {"answer": answer}

        # 有工具调用 → 检查写操作 HITL
        write_calls = [c for c in tool_calls if registry.is_write_tool(c["name"])]
        if write_calls and not state.get("confirmed"):
            confirm_id = f"CFM-{int(time.time() * 1000)}"
            pending = {"confirm_id": confirm_id, "tool_calls": tool_calls}
            await emit("confirmation_request", {
                "confirm_id": confirm_id,
                "tools": [
                    {"name": c["name"], "args": c["args"],
                     "description": (registry.get(c["name"]).description if registry.get(c["name"]) else c["name"])}
                    for c in write_calls
                ],
                "message": "即将写入宝宝数据，请确认",
            })
            return {"pending_write": pending}  # route_after_agent → wait_confirm → END

        # 写操作已确认 → 标记执行所有调用(含读)
        return {"tool_calls": tool_calls}

    return agent_node


def route_after_agent(state: AssistantState) -> Literal["tools", "wait_confirm", "end"]:
    """
    Agent 后路由 (状态机条件分支):
    - pending_write 非空 → wait_confirm (HITL 暂停出口)
    - 有 tool_calls → tools (ReAct 循环)
    - 否则 agent 已直接回答/总结 (answer 已推送) → end
    """
    if state.get("pending_write"):
        return "wait_confirm"
    if state.get("tool_calls"):
        return "tools"
    return "end"


def make_tool_exec_node(ws, emit, idem=None):
    """
    工具执行节点:
    - 幂等: 写操作以 request_id+tool+args 为键去重 (example/idempotent.py 落地)
    - 隔离: 强制注入 user_id, LLM 无法伪造身份
    - 可观测: tool_call / tool_result 事件
    """
    registry = get_registry()
    AIMessage = _init_lc()["AIMessage"]
    ToolMessage = _init_lc()["ToolMessage"]

    async def tool_exec_node(state: AssistantState) -> Dict[str, Any]:
        tool_calls: List[Dict] = state.get("tool_calls") or []
        # HITL 恢复场景: 从 confirmed_call 取
        if state.get("resume") and state.get("confirmed_call"):
            tool_calls = state["confirmed_call"]

        user_id = int(state["user_id"])
        request_id = state.get("request_id") or ""
        trace = list(state.get("tool_trace") or [])
        messages = list(state.get("messages") or [])

        # 追加 AIMessage(tool_calls) 到消息历史, 供 ToolMessage 配对
        messages.append(AIMessage(
            content="",
            tool_calls=[{"name": c["name"], "args": c["args"], "id": c.get("id") or f"c{i}"}
                        for i, c in enumerate(tool_calls)],
        ))

        for i, call in enumerate(tool_calls):
            name, args = call["name"], dict(call.get("args") or {})
            call_id = call.get("id") or f"c{i}"
            # 注入真实身份与幂等键 (不信任 LLM 传参)
            args["user_id"] = user_id
            args.setdefault("request_id", request_id)

            await emit("tool_call", {"id": call_id, "name": name, "args": {
                k: v for k, v in args.items() if k != "user_id"}})

            # 幂等检查 (仅写操作)
            idem_key = None
            if idem and registry.is_write_tool(name):
                idem_key = idem.tool_key(request_id, name, args)
                cached = idem.get_cached(idem_key)
                if cached is not None:
                    await emit("tool_result", {
                        "id": call_id, "name": name,
                        "result": "【幂等命中】该记录已存在，未重复写入",
                        "cached": True})
                    messages.append(ToolMessage(content=json.dumps(
                        {"ok": True, "cached": True, "data": cached}, ensure_ascii=False),
                        tool_call_id=call_id))
                    trace.append({"name": name, "cached": True})
                    continue

            # 执行 (同步 SQLAlchemy → to_thread)
            result = await asyncio.to_thread(registry.execute, name, args)
            data = result.get("data") if result.get("ok") else None

            # 写操作成功 → 存幂等结果
            if idem and idem_key and result.get("ok"):
                idem.save(idem_key, data or {})

            await emit("tool_result", {
                "id": call_id, "name": name,
                "result": json.dumps(data, ensure_ascii=False, default=str)[:500] if result.get("ok")
                          else f"执行失败: {result.get('error')}",
                "ok": result.get("ok", False),
            })
            messages.append(ToolMessage(content=json.dumps(
                {"ok": result.get("ok"), "data": data, "error": result.get("error")},
                ensure_ascii=False, default=str), tool_call_id=call_id))
            trace.append({"name": name, "ok": result.get("ok")})

        # 清理标记，回 agent 总结
        return {
            "messages": messages,
            "tool_calls": None,
            "pending_write": None,
            "confirmed_call": None,
            "resume": False,
            "tool_trace": trace,
            "tool_rounds": (state.get("tool_rounds") or 0) + 1,
        }

    return tool_exec_node


# ── RAG 节点 (复用现有 ChromaDB 知识库, 流式生成) ──────────────

def make_rag_node(ws, emit):
    SystemMessage = _init_lc()["SystemMessage"]

    def _retrieve(query: str):
        from ..ws.rag_query import get_chroma_collection, get_embedding_function
        collection = get_chroma_collection()
        embedding = get_embedding_function().embed_query(query)
        return collection.query(query_embeddings=embedding, n_results=3)

    async def rag_node(state: AssistantState) -> Dict[str, Any]:
        query = state["query"]
        await emit("retrieve_start", {"query": query})

        try:
            results = await asyncio.to_thread(_retrieve, query)
        except Exception as e:
            logger.warning(f"RAG retrieve failed: {e}")
            results = None

        context, sources = "", []
        if results and results.get("documents"):
            for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
                sources.append({
                    "index": i + 1,
                    "title": meta.get("title", ""),
                    "filename": meta.get("filename", ""),
                })
                context += f"【文档{i+1}】{meta.get('title','')}\n{doc}\n\n"
        await emit("retrieve_done", {"count": len(sources), "sources": sources})

        system = SystemMessage(content=(
            "你是专业的育儿知识助手。根据知识库内容回答问题。\n"
            "1. 优先使用知识库信息; 没有则明确说明\n"
            "2. 回答简洁准确, 可引用来源\n"
            f"{state.get('baby_context', '')}\n"
            f"知识库内容:\n{context or '(知识库未返回内容)'}"
        ))
        try:
            llm = _make_llm(streaming=True)
            full = ""
            async for chunk in get_llm_breaker().call_stream(llm.astream,
                                                      [system, _init_lc()["HumanMessage"](content=query)]):
                if chunk.content:
                    full += chunk.content
                    await emit("generate_chunk", {"chunk": chunk.content})
        except CircuitOpenError:
            full = "【系统降级】AI 服务暂时不可用，请稍后重试。"
            await emit("generate_chunk", {"chunk": full})

        await emit("answer_done", {"answer": full, "sources": sources})
        return {"answer": full, "sources": sources}

    return rag_node


# ── 闲聊 / 兜底节点 ───────────────────────────────────────────

def make_chitchat_node(ws, emit, fallback: bool = False):
    SystemMessage = _init_lc()["SystemMessage"]

    async def chitchat_node(state: AssistantState) -> Dict[str, Any]:
        query = state["query"]
        history = state.get("messages") or []
        prefix = "抱歉，我不太理解您的意思。" if fallback else ""
        system = SystemMessage(content=(
            f"{prefix}你是宝宝养育助手 Assistant，友好简洁地回复用户。"
            "可以顺带介绍你能帮用户查询/记录: 喂奶、体温、睡眠、尿不湿、花费、"
            "身高体重、疫苗、生日提醒。\n"
            f"{state.get('baby_context', '')}"
        ))
        try:
            llm = _make_llm(streaming=True)
            full = ""
            async for chunk in get_llm_breaker().call_stream(
                    llm.astream, [system] + history + [_init_lc()["HumanMessage"](content=query)]):
                if chunk.content:
                    full += chunk.content
                    await emit("generate_chunk", {"chunk": chunk.content})
        except CircuitOpenError:
            full = "【系统降级】AI 服务暂时不可用，请稍后重试。"
            await emit("generate_chunk", {"chunk": full})

        await emit("answer_done", {"answer": full})
        return {"answer": full}

    return chitchat_node


# ──────────────────────────────────────────────
# 图编译
# ──────────────────────────────────────────────

def build_assistant_graph(ws=None, idem=None):
    """
    编译完整 LangGraph (每次 WS 连接创建一次, 节点闭包捕获该连接的 ws 与 idem)

    Args:
        ws: FastAPI WebSocket (事件推送; None 时用于离线测试)
        idem: 连接级 IdempotencyManager (写操作幂等)

    Returns:
        compiled graph: await graph.ainvoke(initial_state)
    """
    lc = _init_lc()
    StateGraph = lc["StateGraph"]
    START, END = lc["START"], lc["END"]

    async def emit(event_type, data):
        await _emit(ws, event_type, data)

    workflow = StateGraph(AssistantState)

    workflow.add_node("entry", make_entry_node(ws, emit))
    workflow.add_node("agent", make_agent_node(ws, emit))
    workflow.add_node("tools", make_tool_exec_node(ws, emit, idem=idem))
    workflow.add_node("rag", make_rag_node(ws, emit))
    workflow.add_node("chitchat", make_chitchat_node(ws, emit))
    workflow.add_node("fallback", make_chitchat_node(ws, emit, fallback=True))

    workflow.add_edge(START, "entry")

    # 动态路由: 意图 → 专职 Agent; HITL resume 直通 tools
    def route_entry(state):
        if state.get("resume") and state.get("confirmed_call"):
            return "tools"
        return route_after_intent(state)

    workflow.add_conditional_edges("entry", route_entry, {
        "agent": "agent",
        "rag": "rag",
        "chitchat": "chitchat",
        "fallback": "fallback",
        "tools": "tools",
    })

    # ReAct 循环核心: agent → (tools | wait_confirm | end)
    workflow.add_conditional_edges("agent", route_after_agent, {
        "tools": "tools",
        "wait_confirm": END,       # HITL 暂停: 图结束, WS 层等用户确认后 resume
        "end": END,                # agent 已直接回答 (无工具 / 工具后总结)
    })

    workflow.add_edge("tools", "agent")   # ReAct: 工具执行完回 agent 总结
    workflow.add_edge("rag", END)
    workflow.add_edge("chitchat", END)
    workflow.add_edge("fallback", END)

    return workflow.compile()


def make_resume_state(prev_state: AssistantState, confirmed: bool) -> AssistantState:
    """HITL 恢复: 用户确认后从暂停点继续 (example/hitl.py 的 Command(resume=...) 等价实现)"""
    if not confirmed:
        return {**prev_state, "resume": True, "confirmed": False, "confirmed_call": None}
    return {
        **prev_state,
        "resume": True,
        "confirmed": True,
        "confirmed_call": (prev_state.get("pending_write") or {}).get("tool_calls"),
        "pending_write": None,
    }
