"""
Baby Assistant 完整 LangGraph 实现 (生产版)

生产化重构要点 (vs 旧版):
- 全局编译图: 进程启动时编译一次, 节点不再闭包捕获 ws
- contextvar 注入: emit 回调/身份通过 runtime.py 在运行时传递
- LLM 网关: 所有 LLM 调用走 llm_gateway (多 profile 路由/熔断分桶/计量)
- 原生 interrupt: 写操作 HITL 在独立纯函数节点 confirm 中 interrupt() 暂停
  (与 LLM 决策解耦 — resume 重放节点时确定性返回恢复值, 不会重复调 LLM)
- ReAct 上限: route_after_agent 检查 tool_rounds, 超限走 give_up
- 统一 RAG: rag 节点改用 RetrievalService (混合检索), 不再内联纯向量
- to_thread: 所有同步 IO (SQLAlchemy/embedding/BM25) 包裹, 不阻塞事件循环

图结构:
                    ┌─────────────┐
     START ───────▶ │ entry_node  │  加载宝宝上下文 + 意图识别(两级: 规则→LLM)
                    └──────┬──────┘
                    route_after_intent (conditional_edges 动态路由)
           ┌───────────────┼──────────────────┐
           ▼               ▼                  ▼
     ┌──────────┐   ┌───────────┐     ┌───────────┐
     │  agent   │   │    rag    │     │  chitchat │
     │(LLM 决策)│   │(统一检索) │     │ (流式闲聊) │
     └────┬─────┘   └─────┬─────┘     └─────┬─────┘
          ▼               │                 │
     ┌──────────┐         │                 │
     │ confirm  │  写操作→interrupt暂停 (纯函数节点, 无 LLM, 重放确定)
     └────┬─────┘         │                 │
   route_after_agent      │                 │
    ┌──────┼──────────┐   │                 │
    ▼      ▼          ▼   ▼                 ▼
 ┌──────┐ ┌───────┐ ┌──────┐
 │tools │ │give_up│ │ end  │  reject→end(已取消) / 无写操作直接放行
 └──┬───┘ └───┬───┘ └──┬───┘  tools 完成回到 agent 继续推理
    └────────▶│       │
              ▼       ▼
             END     END
"""

import asyncio
import json
from datetime import date
from typing import Any, Dict, List, Literal, Optional, TypedDict

from loguru import logger

from .resilience import CircuitOpenError, IdempotencyManager
from .runtime import emit, get_runtime_context
from .tool_registry import ToolRegistry, build_default_registry

# ──────────────────────────────────────────────
# LangChain / LangGraph 懒加载
# ──────────────────────────────────────────────

_lc = {}


def _init_lc():
    if _lc:
        return _lc
    from langchain_core.messages import (
        AIMessage, HumanMessage, SystemMessage, ToolMessage,
    )
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt

    _lc.update({
        "AIMessage": AIMessage,
        "HumanMessage": HumanMessage,
        "SystemMessage": SystemMessage,
        "ToolMessage": ToolMessage,
        "StateGraph": StateGraph,
        "START": START,
        "END": END,
        "interrupt": interrupt,
    })
    return _lc


MAX_TOOL_ROUNDS = 5          # ReAct 最大循环轮数(防失控)
CONFIDENCE_THRESHOLD = 0.6   # 意图置信度阈值，低于走 fallback

# 模块级共享: 工具注册中心 (进程级单例)
_REGISTRY: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_default_registry()
    return _REGISTRY


# ──────────────────────────────────────────────
# State 定义 (LangGraph 状态机)
# ──────────────────────────────────────────────

class AssistantState(TypedDict, total=False):
    # 基础 (由 WS 层注入, 不信任 LLM)
    user_id: int
    query: str
    request_id: str

    # 会话
    messages: List[Any]                # langchain messages (含多轮历史, 由 checkpointer 持久化)

    # 意图与路由
    intent: str                        # data_query / knowledge_qa / chitchat
    confidence: float
    slots: Dict[str, Any]
    route: str

    # 上下文
    baby_context: str                  # 宝宝信息 + 今日日期 (注入 system prompt)

    # 工具链路
    tool_rounds: int
    tool_calls: Optional[List[Dict[str, Any]]]
    tool_trace: List[Dict[str, Any]]

    # 输出
    answer: str
    sources: List[Dict[str, Any]]
    error: str


# ──────────────────────────────────────────────
# 意图识别: 规则优先 → LLM 兜底
# ──────────────────────────────────────────────

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
    """第一级: 规则意图识别 (零延迟零成本)"""
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

    import re
    if re.search(r"(记录|记一下|添加|记)", query):
        return {"intent": "data_query", "confidence": 0.85, "slots": {}}
    if re.search(r"\d+(\.\d+)?\s*(ml|毫升|度|kg|公斤|厘米|cm)", q):
        return {"intent": "data_query", "confidence": 0.75, "slots": {}}

    return None


async def _llm_intent(query: str) -> Dict[str, Any]:
    """第二级: LLM few-shot 意图分类 (廉价小模型)"""
    HumanMessage = _init_lc()["HumanMessage"]
    from .llm_gateway import get_llm_gateway

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
        gw = get_llm_gateway()
        resp = await gw.ainvoke("intent", [HumanMessage(content=prompt)])
        text = (resp.content or "").strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            return {
                "intent": parsed.get("intent", "chitchat"),
                "confidence": float(parsed.get("confidence", 0.5)),
                "slots": parsed.get("slots", {}),
            }
    except CircuitOpenError:
        logger.warning("intent LLM circuit open, falling back")
    except Exception as e:
        logger.warning(f"llm_intent failed: {e}")
    return {"intent": "knowledge_qa", "confidence": 0.55, "slots": {}}


# ──────────────────────────────────────────────
# 图节点实现 (plain async functions, 通过 contextvar 获取 emit)
# ──────────────────────────────────────────────

MAX_MEMORY_MESSAGES = 20  # checkpointer 持久化的多轮上下文上限


async def entry_node(state: AssistantState) -> Dict[str, Any]:
    """入口节点: 加载宝宝上下文 + 两级意图识别 + 持久化用户消息"""
    query = state["query"]
    await emit("intent_start", {"query": query})

    # 加载宝宝上下文 (数据级鉴权: 仅查当前 user)
    baby_context = await _load_baby_context(state["user_id"])

    # 两级意图识别
    rule = _rule_intent(query)
    if rule:
        intent_res = rule
    else:
        intent_res = await _llm_intent(query)

    intent = intent_res["intent"]
    confidence = intent_res["confidence"]
    if confidence < CONFIDENCE_THRESHOLD:
        intent = "chitchat"

    # 持久化用户消息 (checkpointer 跨连接承载多轮记忆)
    HumanMessage = _init_lc()["HumanMessage"]
    messages = list(state.get("messages") or [])
    messages.append(HumanMessage(content=query))
    messages = messages[-MAX_MEMORY_MESSAGES:]

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
        "messages": messages,
    }


async def _load_baby_context(user_id: int) -> str:
    from .repository import BabyDataRepository
    from ..core.database import SessionLocal
    try:
        repo = await asyncio.to_thread(lambda: BabyDataRepository(SessionLocal()))
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


def route_after_intent(state: AssistantState) -> Literal["agent", "rag", "chitchat", "fallback"]:
    """动态路由: 声明式 intent→node 映射"""
    route_map = {
        "data_query": "agent",
        "knowledge_qa": "rag",
        "chitchat": "chitchat",
    }
    return route_map.get(state.get("intent"), "fallback")


# ── 数据 Agent 节点 (Function Calling ReAct 循环) ──────────────

async def agent_node(state: AssistantState) -> Dict[str, Any]:
    """Agent 节点: LLM 决策 (带工具绑定), 输出 tool_calls 或直接回答。

    注意: 本节点不含 interrupt() — HITL 在 confirm_node (纯函数) 中处理,
    避免 resume 重放节点时重复调用 LLM / 决策漂移。
    """
    SystemMessage = _init_lc()["SystemMessage"]
    registry = get_registry()
    schemas = registry.get_schemas_for_llm()

    query = state["query"]
    # messages 已由 entry_node 追加当前用户消息 (checkpointer 持久化)
    messages = list(state.get("messages") or [])[-MAX_MEMORY_MESSAGES:]

    system = (
        "你是宝宝养育助手 Assistant。可以调用工具查询和记录宝宝数据。\n"
        f"{state.get('baby_context', '')}\n"
        "规则:\n"
        "1. 数据查询/记录必须调用对应工具，不要编造数据\n"
        "2. 记录类输入信息不全时用默认值补全后直接调用写工具: 时间默认现在;"
        "喂奶类型未说明默认 bottle; 确认卡片会展示全部参数(含默认时间), "
        "用户可在确认时修改或指定时间。只有缺少关键数值(奶量/体温/金额等)时才追问\n"
        "3. 拿到工具结果后，用简洁友好的中文总结给用户\n"
        "4. 一次只调用必要的工具\n"
    )
    msgs = [SystemMessage(content=system)] + messages

    try:
        from .llm_gateway import get_llm_gateway
        gw = get_llm_gateway()
        # 统一走网关: 工具绑定 + 熔断分桶 + 备用模型降级
        resp = await gw.ainvoke_with_tools("agent", schemas, msgs)
    except CircuitOpenError:
        return {"answer": "【系统降级】AI 服务暂时不可用，请稍后重试。", "route": "agent"}

    tool_calls = list(getattr(resp, "tool_calls", None) or [])

    # 无工具调用 → 直接回答
    if not tool_calls:
        answer = resp.content or "我在呢，请问想查询或记录什么数据？"
        await emit("generate_chunk", {"chunk": answer})
        await emit("answer_done", {"answer": answer, "tool_trace": state.get("tool_trace", [])})
        AIMessage = _init_lc()["AIMessage"]
        return {
            "answer": answer,
            "messages": (messages + [AIMessage(content=answer)])[-MAX_MEMORY_MESSAGES:],
        }

    # 有工具调用 → 交由 confirm 节点做 HITL 确认门 (读操作直接放行)
    return {"tool_calls": tool_calls}


# 写工具的时间类参数 → 缺省解析值 ("now_dt"=现在时刻, "today"=今天日期)
_TIME_PARAM_DEFAULTS = {
    "feed_time": "now_dt", "sleep_time": "now_dt", "use_date": "now_dt",
    "order_time": "now_dt", "actual_date": "today", "measure_date": "today",
    "day": "today",
}


def _confirm_summary(write_calls) -> str:
    """把待执行的写操作渲染成人读摘要; 时间类参数缺省时显式展示 '现在' 值。

    用户需求: 说'喝奶150ml'后, 确认卡片要能回答 '是现在时间吗, 还是指定时间?' —
    因此默认时间必须出现在确认消息里, 而不是藏在工具内部。
    """
    from datetime import datetime
    registry = get_registry()
    now = datetime.now()
    lines = []
    for c in write_calls:
        args = c.get("args") or {}
        meta = registry.get(c["name"])
        declared = set(((meta.parameters if meta else None) or {}).get("properties") or {})
        parts = [f"{k}={v}" for k, v in args.items() if v not in (None, "")]
        defaults = [
            f"{k}=现在({now:%H:%M})" if mode == "now_dt" else f"{k}=今天({now:%Y-%m-%d})"
            for k, mode in _TIME_PARAM_DEFAULTS.items()
            if not args.get(k) and k in declared
        ]
        detail = "，".join(parts + defaults) or "无参数"
        lines.append(f"· {c['name']}: {detail}")
    return "\n".join(lines)


async def confirm_node(state: AssistantState) -> Dict[str, Any]:
    """HITL 确认门 (纯函数节点): state.tool_calls 含写操作时 interrupt() 暂停。

    为什么单独拆节点: LangGraph resume 时会从头重放 interrupt 所在节点,
    若节点内含 LLM 调用则重放结果不确定 (可能不再产生相同 tool_calls)。
    本节点只读 state + interrupt(), 重放是确定性的 → 恢复值稳定返回。
    """
    registry = get_registry()
    interrupt_fn = _init_lc()["interrupt"]
    AIMessage = _init_lc()["AIMessage"]

    tool_calls = list(state.get("tool_calls") or [])
    write_calls = [c for c in tool_calls if registry.is_write_tool(c["name"])]
    if not write_calls:
        return {}  # 纯读操作: 直接放行

    import uuid
    confirm_id = f"CFM-{uuid.uuid4().hex}"
    # 原生 interrupt: 图暂停, checkpointer 持久化状态
    decision = interrupt_fn({
        "confirm_id": confirm_id,
        "tools": [
            {"name": c["name"], "args": c["args"],
             "description": (registry.get(c["name"]).description if registry.get(c["name"]) else c["name"])}
            for c in write_calls
        ],
        "message": ("即将写入宝宝数据，请确认"
                    "（时间未指定时默认为现在，可在确认时修改）:\n"
                    + _confirm_summary(write_calls)),
    })
    # 用户 reject → 直接取消
    if decision.get("action") == "reject":
        answer = "好的，已取消本次操作。"
        return {
            "answer": answer,
            "tool_calls": None,
            "messages": (list(state.get("messages") or [])
                         + [AIMessage(content=answer)])[-MAX_MEMORY_MESSAGES:],
        }
    # approve → 继续执行 (可带用户修改后的参数)
    # 如果用户修改了参数, decision 里会带 modified_args
    if decision.get("modified_args"):
        for c in tool_calls:
            if c["name"] in decision["modified_args"]:
                c["args"].update(decision["modified_args"][c["name"]])
    return {"tool_calls": tool_calls}


def route_after_agent(state: AssistantState) -> Literal["tools", "end", "give_up"]:
    """
    Agent 后路由 (状态机条件分支):
    - 有 tool_calls 且未超轮数上限 → tools (ReAct 循环)
    - 有 tool_calls 但超限 → give_up (兜底降级)
    - 否则 agent 已直接回答 → end
    """
    if state.get("tool_calls"):
        if (state.get("tool_rounds") or 0) >= MAX_TOOL_ROUNDS:
            return "give_up"
        return "tools"
    return "end"


async def tool_exec_node(state: AssistantState) -> Dict[str, Any]:
    """
    工具执行节点 (纯函数, 通过 contextvar 获取身份):
    - 幂等: 写操作以 request_id+tool+args 为键去重 (Redis)
    - 隔离: 强制注入 user_id
    - 可观测: tool_call / tool_result 事件
    """
    registry = get_registry()
    AIMessage = _init_lc()["AIMessage"]
    ToolMessage = _init_lc()["ToolMessage"]
    ctx = get_runtime_context()

    tool_calls: List[Dict] = state.get("tool_calls") or []
    user_id = int(state["user_id"])
    request_id = ctx.request_id or state.get("request_id") or ""
    trace = list(state.get("tool_trace") or [])
    messages = list(state.get("messages") or [])

    # 追加 AIMessage(tool_calls) 到消息历史
    messages.append(AIMessage(
        content="",
        tool_calls=[{"name": c["name"], "args": c["args"], "id": c.get("id") or f"c{i}"}
                    for i, c in enumerate(tool_calls)],
    ))

    # 幂等管理器 (Redis-backed, URL 来自统一配置)
    from ..core.config import get_settings
    idem = IdempotencyManager(redis_url=get_settings().redis_url)

    for i, call in enumerate(tool_calls):
        name, args = call["name"], dict(call.get("args") or {})
        call_id = call.get("id") or f"c{i}"
        args["user_id"] = user_id
        args.setdefault("request_id", request_id)

        await emit("tool_call", {"id": call_id, "name": name, "args": {
            k: v for k, v in args.items() if k != "user_id"}})

        # 幂等检查 (仅写操作)
        idem_key = None
        if registry.is_write_tool(name):
            idem_key = IdempotencyManager.tool_key(request_id, name, args)
            cached = await idem.get_cached(idem_key)
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

        # 执行 (同步 SQLAlchemy → to_thread, 不阻塞事件循环)
        result = await asyncio.to_thread(registry.execute, name, args)
        data = result.get("data") if result.get("ok") else None

        # 写操作成功 → 存幂等结果
        if idem_key and result.get("ok"):
            await idem.save(idem_key, data or {})

        await emit("tool_result", {
            "id": call_id, "name": name,
            "result": json.dumps(data, ensure_ascii=False, default=str)[:500] if result.get("ok")
                      else f"执行失败: {result.get('error')}",
            "ok": result.get("ok", False),
            "retry_hint": result.get("retry_hint", False),
        })
        messages.append(ToolMessage(content=json.dumps(
            {"ok": result.get("ok"), "data": data, "error": result.get("error")},
            ensure_ascii=False, default=str), tool_call_id=call_id))
        trace.append({"name": name, "ok": result.get("ok")})

    return {
        "messages": messages,
        "tool_calls": None,
        "tool_trace": trace,
        "tool_rounds": (state.get("tool_rounds") or 0) + 1,
    }


# ── RAG 节点 (统一检索服务, 混合检索 + 精排 + 流式生成) ──────────

async def rag_node(state: AssistantState) -> Dict[str, Any]:
    """RAG 节点: 使用 RetrievalService 统一混合检索 (不再内联纯向量)"""
    SystemMessage = _init_lc()["SystemMessage"]
    HumanMessage = _init_lc()["HumanMessage"]
    ctx = get_runtime_context()

    query = state["query"]
    await emit("retrieve_start", {"query": query})

    try:
        from ..rag.service import RetrievalService, RetrievalRequest, get_retrieval_service
        svc = get_retrieval_service()
        # 从 baby_context 抽月龄传入 (如有)
        age_months = _extract_age_from_context(state.get("baby_context", ""))
        # 多轮历史: 从 messages 提取最近人类消息
        history = _extract_recent_human_msgs(state.get("messages") or [], limit=4)

        req = RetrievalRequest(
            query=query, top_k=3, fetch=20,
            age_months=age_months, history=history,
            enable_rerank=True,
        )
        result = await svc.search(req)

        await emit("retrieve_done", {
            "count": len(result.hits),
            "sources": [{"index": s.index, "title": s.title,
                         "filename": s.filename, "category": s.category}
                        for s in result.sources],
            "debug": result.debug,
        })
    except Exception as e:
        logger.warning(f"RAG retrieve failed: {e}")
        result = None

    context = result.context if result else "(知识库未返回内容)"
    sources = [{"index": s.index, "title": s.title, "filename": s.filename,
                "category": s.category} for s in (result.sources if result else [])]

    system = SystemMessage(content=(
        "你是专业的育儿知识助手。根据知识库内容回答问题。\n"
        "1. 优先使用知识库信息; 没有则明确说明\n"
        "2. 回答简洁准确, 可引用来源 [文档N]\n"
        f"{state.get('baby_context', '')}\n"
        f"知识库内容:\n{context}"
    ))
    try:
        from .llm_gateway import get_llm_gateway
        gw = get_llm_gateway()
        full = ""
        async for chunk in gw.astream("rag", [system, HumanMessage(content=query)]):
            if chunk.content:
                full += chunk.content
                await emit("generate_chunk", {"chunk": chunk.content})
    except CircuitOpenError:
        full = "【系统降级】AI 服务暂时不可用，请稍后重试。"
        await emit("generate_chunk", {"chunk": full})

    await emit("answer_done", {"answer": full, "sources": sources})
    # 持久化回答 (多轮记忆)
    messages = list(state.get("messages") or [])[-MAX_MEMORY_MESSAGES:]
    AIMessage = _init_lc()["AIMessage"]
    messages.append(AIMessage(content=full))
    return {"answer": full, "sources": sources,
            "messages": messages[-MAX_MEMORY_MESSAGES:]}


def _extract_age_from_context(baby_context: str) -> Optional[float]:
    """从 baby_context 字符串抽取月龄"""
    import re
    m = re.search(r'月龄=(\d+)个月', baby_context)
    if m:
        return float(m.group(1))
    return None


def _extract_recent_human_msgs(messages: List[Any], limit: int = 4) -> List[str]:
    """从 langchain messages 提取最近的人类消息文本 (用于多轮改写)"""
    from langchain_core.messages import HumanMessage
    texts = []
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) and msg.content:
            texts.insert(0, str(msg.content))
            if len(texts) >= limit:
                break
    return texts


# ── 闲聊 / 兜底节点 ───────────────────────────────────────────

async def chitchat_node(state: AssistantState) -> Dict[str, Any]:
    SystemMessage = _init_lc()["SystemMessage"]

    query = state["query"]
    # entry 已把当前 HumanMessage 追加进 messages
    history = (state.get("messages") or [])[-MAX_MEMORY_MESSAGES:]
    system = SystemMessage(content=(
        "你是宝宝养育助手 Assistant，友好简洁地回复用户。"
        "可以顺带介绍你能帮用户查询/记录: 喂奶、体温、睡眠、尿不湿、花费、"
        "身高体重、疫苗、生日提醒。\n"
        f"{state.get('baby_context', '')}"
    ))
    try:
        from .llm_gateway import get_llm_gateway
        gw = get_llm_gateway()
        full = ""
        async for chunk in gw.astream("chitchat", [system] + history):
            if chunk.content:
                full += chunk.content
                await emit("generate_chunk", {"chunk": chunk.content})
    except CircuitOpenError:
        full = "【系统降级】AI 服务暂时不可用，请稍后重试。"
        await emit("generate_chunk", {"chunk": full})

    await emit("answer_done", {"answer": full})
    AIMessage = _init_lc()["AIMessage"]
    return {"answer": full, "messages": (history + [AIMessage(content=full)])[-MAX_MEMORY_MESSAGES:]}


async def fallback_node(state: AssistantState) -> Dict[str, Any]:
    """兜底节点: 低置信度意图, 引导用户明确需求"""
    SystemMessage = _init_lc()["SystemMessage"]

    query = state["query"]
    history = (state.get("messages") or [])[-MAX_MEMORY_MESSAGES:]
    system = SystemMessage(content=(
        "抱歉，我不太理解您的意思。你是宝宝养育助手 Assistant，友好简洁地回复用户。"
        "可以顺带介绍你能帮用户查询/记录: 喂奶、体温、睡眠、尿不湿、花费、"
        "身高体重、疫苗、生日提醒。\n"
        f"{state.get('baby_context', '')}"
    ))
    try:
        from .llm_gateway import get_llm_gateway
        gw = get_llm_gateway()
        full = ""
        async for chunk in gw.astream("chitchat", [system] + history):
            if chunk.content:
                full += chunk.content
                await emit("generate_chunk", {"chunk": chunk.content})
    except CircuitOpenError:
        full = "【系统降级】AI 服务暂时不可用，请稍后重试。"
        await emit("generate_chunk", {"chunk": full})

    await emit("answer_done", {"answer": full})
    AIMessage = _init_lc()["AIMessage"]
    return {"answer": full, "messages": (history + [AIMessage(content=full)])[-MAX_MEMORY_MESSAGES:]}


async def give_up_node(state: AssistantState) -> Dict[str, Any]:
    """ReAct 超限兜底: 告知用户已执行的操作, 避免静默失败"""
    trace = state.get("tool_trace") or []
    done = [t["name"] for t in trace if t.get("ok")]
    summary = "、".join(done) if done else "无"
    answer = (
        f"本轮操作较复杂（已执行: {summary}），"
        "请换个说法或拆分问题后再试，我会继续帮你处理。"
    )
    await emit("generate_chunk", {"chunk": answer})
    await emit("answer_done", {"answer": answer, "tool_trace": trace})
    history = (state.get("messages") or [])[-MAX_MEMORY_MESSAGES:]
    AIMessage = _init_lc()["AIMessage"]
    return {
        "answer": answer,
        "messages": (history + [AIMessage(content=answer)])[-MAX_MEMORY_MESSAGES:],
    }


# ──────────────────────────────────────────────
# 图编译 (全局共享, 进程启动时编译一次)
# ──────────────────────────────────────────────

def build_assistant_graph(checkpointer=None):
    """
    编译 LangGraph (进程级共享, 不再 per-connection)

    Args:
        checkpointer: LangGraph checkpointer (MemorySaver/Redis/Postgres)
                      None 时用 MemorySaver (进程内, 不跨实例)

    Returns:
        compiled graph
    """
    lc = _init_lc()
    StateGraph = lc["StateGraph"]
    START, END = lc["START"], lc["END"]

    # 默认 MemorySaver (生产应替换为 Redis/Postgres checkpointer)
    if checkpointer is None:
        try:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
            logger.info("Using MemorySaver (in-process, not production-safe)")
        except Exception:
            logger.warning("No checkpointer available, graph runs stateless")
            checkpointer = None

    workflow = StateGraph(AssistantState)

    # 注册节点 (plain functions, 不再工厂闭包)
    workflow.add_node("entry", entry_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("confirm", confirm_node)
    workflow.add_node("tools", tool_exec_node)
    workflow.add_node("rag", rag_node)
    workflow.add_node("chitchat", chitchat_node)
    workflow.add_node("fallback", fallback_node)
    workflow.add_node("give_up", give_up_node)

    workflow.add_edge(START, "entry")

    # 动态路由: 意图 → 专职节点
    workflow.add_conditional_edges("entry", route_after_intent, {
        "agent": "agent",
        "rag": "rag",
        "chitchat": "chitchat",
        "fallback": "fallback",
    })

    # ReAct 循环核心: agent → confirm (HITL 门) → (tools | give_up | end)
    # interrupt 暂停发生在 confirm 节点 (纯函数), 恢复重放确定性
    workflow.add_edge("agent", "confirm")
    workflow.add_conditional_edges("confirm", route_after_agent, {
        "tools": "tools",
        "give_up": "give_up",
        "end": END,                # agent 已直接回答 (无工具 / 工具后总结 / reject 已取消)
    })

    workflow.add_edge("tools", "agent")   # ReAct: 工具执行完回 agent 总结
    workflow.add_edge("rag", END)
    workflow.add_edge("chitchat", END)
    workflow.add_edge("fallback", END)
    workflow.add_edge("give_up", END)

    return workflow.compile(checkpointer=checkpointer) if checkpointer else workflow.compile()


# ──────────────────────────────────────────────
# 进程级单例 (全局共享图)
# ──────────────────────────────────────────────

_compiled_graph = None
_checkpointer = None


def init_graph_checkpointer() -> str:
    """初始化 checkpointer: Redis 优先, 失败回退 MemorySaver (启动早期调用)。

    必须在 main.py include_router 之前同步调用 — 路由工厂在 import 期
    就会 get_compiled_graph() 编图, 晚了会捕获到 MemorySaver。
    Redis 为纯社区版 6.2 (无 RediSearch), 用自研 RedisCheckpointer 而非官方包。
    """
    global _checkpointer
    try:
        from ..core.config import get_settings
        from .redis_checkpointer import RedisCheckpointer
        cp = RedisCheckpointer(redis_url=get_settings().redis_url)
        cp.ping()
        _checkpointer = cp
        logger.info("[assistant_graph] checkpointer=RedisCheckpointer "
                    f"(redis={get_settings().redis_url.split('@')[-1]})")
        return "redis"
    except Exception as e:
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer = MemorySaver()
        logger.warning(f"[assistant_graph] Redis checkpointer 不可用 "
                       f"({type(e).__name__}: {e}), 回退 MemorySaver (进程内)")
        return "memory"


def get_compiled_graph():
    """获取进程级共享编译图 (启动时编译一次)"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_assistant_graph(_checkpointer)
    return _compiled_graph
