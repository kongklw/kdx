"""
动态路由 (Dynamic Routing)
==========================

核心概念：
  Agent 系统收到用户请求后，根据意图识别结果，动态决定将请求路由到
  哪个下游处理节点（RAG Agent / 预约 Agent / 闲聊 Agent）。

  动态路由 vs 硬编码路由：
  - 硬编码: if intent == "vaccine": call_vaccine_agent()
  - 动态:   router.dispatch(intent, payload)  ← 路由表可配置、可热更新

在 LangGraph 中的实现：
  - 使用 conditional_edges 做条件路由
  - 路由函数返回下一个节点名称
  - 支持多级路由（意图 → 子意图 → 具体 Agent）

面试话术：
  "我们的路由层基于意图识别结果做动态分发。
   路由表是声明式配置的，支持热更新——新增意图时不需要改代码，
   只需要在路由表中注册 intent → handler 的映射关系。
   在 LangGraph 中用 conditional_edges 实现，路由函数返回节点名，
   图引擎自动跳转。对于低置信度的意图，统一路由到兜底 Agent。"
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, Callable, Optional, List
from enum import Enum

from .intent_recognition import recognize_intent, IntentResult


# ──────────────────────────────────────────────
# 路由上下文
# ──────────────────────────────────────────────

@dataclass
class RouteContext:
    """路由上下文，贯穿整个处理链路"""
    user_id: str
    text: str
    intent_result: Optional[IntentResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)  # 透传的上下文信息
    history: List[str] = field(default_factory=list)        # 处理历史，用于追踪


# ──────────────────────────────────────────────
# Agent 处理器（每个意图对应一个）
# ──────────────────────────────────────────────

async def vaccine_agent(ctx: RouteContext) -> str:
    """疫苗查询 Agent"""
    return f"[疫苗Agent] 查询疫苗信息: 槽位={ctx.intent_result.slots}"


async def feeding_agent(ctx: RouteContext) -> str:
    """喂养建议 Agent"""
    return f"[喂养Agent] 查询喂养建议: 槽位={ctx.intent_result.slots}"


async def development_agent(ctx: RouteContext) -> str:
    """发育查询 Agent"""
    return f"[发育Agent] 查询发育指标: 槽位={ctx.intent_result.slots}"


async def appointment_agent(ctx: RouteContext) -> str:
    """预约挂号 Agent"""
    return f"[预约Agent] 预约门诊: 槽位={ctx.intent_result.slots}"


async def chitchat_agent(ctx: RouteContext) -> str:
    """闲聊 Agent（兜底）"""
    return f"[闲聊Agent] 通用回复"


async def fallback_agent(ctx: RouteContext) -> str:
    """兜底 Agent（意图识别失败时）"""
    return f"[兜底Agent] 抱歉，我无法理解您的需求，请尝试换一种问法。"


# ──────────────────────────────────────────────
# 动态路由器
# ──────────────────────────────────────────────

class DynamicRouter:
    """
    声明式动态路由器

    特点：
    1. 路由表可配置：通过 register() 注册新的 intent → handler
    2. 支持热更新：不修改代码即可调整路由
    3. 兜底机制：未注册的意图自动走 fallback
    4. 可观测：记录路由决策日志
    """

    def __init__(self):
        self._routes: Dict[str, Callable] = {}
        self._fallback: Callable = fallback_agent
        self._route_log: List[Dict] = []

    def register(self, intent: str, handler: Callable):
        """注册意图 → 处理器映射"""
        self._routes[intent] = handler

    def set_fallback(self, handler: Callable):
        """设置兜底处理器"""
        self._fallback = handler

    async def dispatch(self, ctx: RouteContext) -> str:
        """
        路由分发

        决策流程：
        1. 检查意图识别结果是否存在
        2. 检查置信度是否达标（阈值 0.7）
        3. 在路由表中查找对应的 handler
        4. 找不到 → 走兜底
        """
        intent_result = ctx.intent_result

        # 意图识别失败
        if intent_result is None:
            self._log_route(ctx, "no_intent", "fallback")
            return await self._fallback(ctx)

        # 置信度过低 → 兜底
        if intent_result.confidence < 0.7:
            self._log_route(ctx, intent_result.intent, "low_confidence_fallback")
            return await self._fallback(ctx)

        # 查路由表
        handler = self._routes.get(intent_result.intent)
        if handler is None:
            self._log_route(ctx, intent_result.intent, "no_handler_fallback")
            return await self._fallback(ctx)

        # 正常路由
        self._log_route(ctx, intent_result.intent, "routed")
        return await handler(ctx)

    def _log_route(self, ctx: RouteContext, intent: str, decision: str):
        """记录路由决策日志（可观测性）"""
        entry = {
            "user_id": ctx.user_id,
            "text": ctx.text[:50],
            "intent": intent,
            "decision": decision,
        }
        self._route_log.append(entry)

    def get_route_log(self) -> List[Dict]:
        return self._route_log


# ──────────────────────────────────────────────
# LangGraph 条件路由示例（伪代码）
# ──────────────────────────────────────────────

LANGGRAPH_CONDITIONAL_ROUTING = """
# === LangGraph 中的动态路由实现 ===

from langgraph.graph import StateGraph, END

def route_by_intent(state):
    \"\"\"路由函数：根据意图返回下一个节点名\"\"\"
    intent = state["intent"]
    confidence = state["confidence"]

    # 低置信度走兜底
    if confidence < 0.7:
        return "fallback_agent"

    # 路由表
    route_map = {
        "query_vaccine": "vaccine_agent",
        "query_feeding": "feeding_agent",
        "query_development": "development_agent",
        "book_appointment": "appointment_agent",
        "chitchat": "chitchat_agent",
    }
    return route_map.get(intent, "fallback_agent")

# 构建图
workflow = StateGraph(AgentState)
workflow.add_node("intent_recognition", recognize_intent_node)
workflow.add_node("vaccine_agent", vaccine_node)
workflow.add_node("feeding_agent", feeding_node)
workflow.add_node("fallback_agent", fallback_node)

# 条件边：意图识别后根据 route_by_intent 的返回值路由
workflow.set_entry_point("intent_recognition")
workflow.add_conditional_edges(
    "intent_recognition",       # 源节点
    route_by_intent,            # 路由函数
    {                           # 路由映射
        "vaccine_agent": "vaccine_agent",
        "feeding_agent": "feeding_agent",
        "fallback_agent": "fallback_agent",
    }
)
workflow.add_edge("vaccine_agent", END)
workflow.add_edge("feeding_agent", END)
workflow.add_edge("fallback_agent", END)

graph = workflow.compile()
"""

# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

import asyncio
async def main():
    # 初始化路由器并注册路由表
    router = DynamicRouter()
    router.register("query_vaccine", vaccine_agent)
    router.register("query_feeding", feeding_agent)
    router.register("query_development", development_agent)
    router.register("book_appointment", appointment_agent)
    router.register("chitchat", chitchat_agent)

    test_inputs = [
        ("user_001", "6个月大的宝宝要打乙肝疫苗吗？"),
        ("user_002", "宝宝不爱吃辅食怎么办"),
        ("user_003", "帮我预约下周三的儿童体检"),
        ("user_004", "今天天气真好"),
        ("user_005", "asdfghjkl"),  # 无法识别
    ]

    print("=" * 60)
    print("动态路由 Demo")
    print("=" * 60)

    for user_id, text in test_inputs:
        # Step 1: 意图识别
        intent_result = await recognize_intent(text)

        # Step 2: 构建路由上下文
        ctx = RouteContext(
            user_id=user_id,
            text=text,
            intent_result=intent_result,
        )

        # Step 3: 动态路由
        result = await router.dispatch(ctx)

        print(f"\n用户: {user_id}")
        print(f"输入: {text}")
        print(f"意图: {ctx.intent_result.intent} (置信度: {ctx.intent_result.confidence})")
        print(f"结果: {result}")

    # 打印路由日志
    print(f"\n{'─' * 40}")
    print("路由决策日志:")
    for entry in router.get_route_log():
        print(f"  {entry}")


if __name__ == "__main__":
    asyncio.run(main())
