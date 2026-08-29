"""
状态机管理 (State Machine Management)
=======================================

核心概念：
  Agent 处理复杂业务时，需要管理多个状态之间的流转。
  状态机定义了：有哪些状态、哪些状态可以转到哪些状态、转换条件是什么。

  在 Agent 系统中的应用场景：
  - 订单/审批流程状态管理
  - 多轮对话状态追踪
  - Agent 工作流节点编排

LangGraph 中的状态机：
  - StateGraph 本质就是一个状态机
  - 节点 = 状态
  - 边 = 状态转换
  - conditional_edges = 条件转换

面试话术：
  "我用 LangGraph StateGraph 管理状态机。
   State 是 TypedDict，包含所有节点共享的字段。
   节点函数接收 state、返回 state 的增量更新。
   conditional_edges 做条件分支——比如审核通过走 next 节点，
   审核不通过走 retry 节点。
   LangGraph 的 checkpoint 机制可以持久化状态，
   支持断点续做和回放。"
"""

import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable


# ──────────────────────────────────────────────
# 状态定义
# ──────────────────────────────────────────────

class OrderState(Enum):
    """订单状态枚举"""
    CREATED = "created"           # 已创建
    PAID = "paid"                # 已支付
    PROCESSING = "processing"    # 处理中
    REVIEWING = "reviewing"      # 审核中
    COMPLETED = "completed"      # 已完成
    CANCELLED = "cancelled"      # 已取消
    REFUNDED = "refunded"        # 已退款


# ──────────────────────────────────────────────
# 状态转换规则（声明式定义）
# ──────────────────────────────────────────────

# 状态转换图: { 当前状态: [(目标状态, 转换条件函数), ...] }
TRANSITIONS: Dict[OrderState, List[tuple]] = {
    OrderState.CREATED: [
        (OrderState.PAID,       "user_paid"),       # 用户支付
        (OrderState.CANCELLED,  "user_cancelled"),   # 用户取消
    ],
    OrderState.PAID: [
        (OrderState.PROCESSING,  "auto_start"),       # 自动开始处理
        (OrderState.REFUNDED,    "refund_request"),   # 退款
    ],
    OrderState.PROCESSING: [
        (OrderState.REVIEWING,   "submit_review"),    # 提交审核
        (OrderState.REFUNDED,    "refund_request"),
    ],
    OrderState.REVIEWING: [
        (OrderState.COMPLETED,   "review_passed"),    # 审核通过
        (OrderState.PROCESSING,  "review_rejected"),  # 审核驳回，重新处理
    ],
    OrderState.COMPLETED: [
        (OrderState.REFUNDED,    "refund_request"),
    ],
    OrderState.CANCELLED: [],
    OrderState.REFUNDED:  [],
}


# ──────────────────────────────────────────────
# 状态机引擎
# ──────────────────────────────────────────────

class StateMachine:
    """
    通用状态机引擎

    特点：
    1. 声明式转换规则
    2. 转换前校验合法性（防止非法跳转）
    3. 转换前后钩子（before/after hook）
    4. 完整的状态变更日志
    """

    def __init__(self, transitions: Dict[Enum, List[tuple]]):
        self._transitions = transitions
        self._before_hooks: Dict[Enum, List[Callable]] = {}
        self._after_hooks: Dict[Enum, List[Callable]] = {}
        self._transition_log: List[Dict] = []

    def on_enter(self, state: Enum, hook: Callable):
        """注册状态进入钩子"""
        self._after_hooks.setdefault(state, []).append(hook)

    def on_exit(self, state: Enum, hook: Callable):
        """注册状态退出钩子"""
        self._before_hooks.setdefault(state, []).append(hook)

    def can_transition(self, current: Enum, target: Enum, event: str) -> bool:
        """检查是否可以从 current 通过 event 转到 target"""
        allowed = self._transitions.get(current, [])
        for (t_state, t_event) in allowed:
            if t_state == target and t_event == event:
                return True
        return False

    def get_valid_transitions(self, current: Enum) -> List[tuple]:
        """获取当前状态的所有合法转换"""
        return self._transitions.get(current, [])

    async def transition(
        self,
        current: Enum,
        target: Enum,
        event: str,
        context: Optional[Dict] = None,
    ) -> Enum:
        """
        执行状态转换

        1. 校验转换合法性
        2. 执行 before hook（退出当前状态）
        3. 执行状态转换
        4. 执行 after hook（进入新状态）
        5. 记录日志
        """
        # 校验
        if not self.can_transition(current, target, event):
            valid = self.get_valid_transitions(current)
            raise ValueError(
                f"非法状态转换: {current.value} → {target.value} (event={event})。"
                f"合法转换: {[(t.value, e) for t, e in valid]}"
            )

        # before hook
        for hook in self._before_hooks.get(current, []):
            await hook(context or {})

        # 记录日志
        self._transition_log.append({
            "from": current.value,
            "to": target.value,
            "event": event,
        })

        # after hook
        for hook in self._after_hooks.get(target, []):
            await hook(context or {})

        return target


# ──────────────────────────────────────────────
# 业务上下文
# ──────────────────────────────────────────────

@dataclass
class OrderContext:
    """订单上下文"""
    order_id: str
    state: OrderState = OrderState.CREATED
    metadata: Dict[str, Any] = field(default_factory=dict)
    history: List[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# 钩子函数示例
# ──────────────────────────────────────────────

async def on_paid_hook(context: Dict):
    """支付成功后的钩子：发送通知"""
    order_id = context.get("order_id", "unknown")
    print(f"  [Hook] 订单 {order_id} 支付成功，发送通知...")

async def on_reviewing_hook(context: Dict):
    """进入审核状态的钩子：通知审核人员"""
    order_id = context.get("order_id", "unknown")
    print(f"  [Hook] 订单 {order_id} 进入审核，通知审核人员...")

async def on_completed_hook(context: Dict):
    """订单完成的钩子"""
    order_id = context.get("order_id", "unknown")
    print(f"  [Hook] 订单 {order_id} 已完成！")


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    # 初始化状态机
    sm = StateMachine(TRANSITIONS)

    # 注册钩子
    sm.on_enter(OrderState.PAID, on_paid_hook)
    sm.on_enter(OrderState.REVIEWING, on_reviewing_hook)
    sm.on_enter(OrderState.COMPLETED, on_completed_hook)

    # 创建订单
    order = OrderContext(order_id="ORD-2026-001")
    print(f"订单 {order.order_id} 创建，初始状态: {order.state.value}")

    # 状态流转：CREATED → PAID
    order.state = await sm.transition(
        OrderState.CREATED, OrderState.PAID, "user_paid",
        context={"order_id": order.order_id},
    )
    order.history.append("user_paid")
    print(f"  当前状态: {order.state.value}")

    # PAID → PROCESSING
    order.state = await sm.transition(
        OrderState.PAID, OrderState.PROCESSING, "auto_start",
        context={"order_id": order.order_id},
    )
    order.history.append("auto_start")
    print(f"  当前状态: {order.state.value}")

    # PROCESSING → REVIEWING
    order.state = await sm.transition(
        OrderState.PROCESSING, OrderState.REVIEWING, "submit_review",
        context={"order_id": order.order_id},
    )
    order.history.append("submit_review")
    print(f"  当前状态: {order.state.value}")

    # REVIEWING → COMPLETED
    order.state = await sm.transition(
        OrderState.REVIEWING, OrderState.COMPLETED, "review_passed",
        context={"order_id": order.order_id},
    )
    order.history.append("review_passed")
    print(f"  当前状态: {order.state.value}")

    # 打印转换日志
    print(f"\n{'─' * 40}")
    print("状态转换日志:")
    for entry in sm._transition_log:
        print(f"  {entry['from']} → {entry['to']} (event: {entry['event']})")

    # 测试非法转换
    print(f"\n测试非法转换:")
    try:
        await sm.transition(OrderState.COMPLETED, OrderState.PROCESSING, "invalid_event")
    except ValueError as e:
        print(f"  ✅ 正确拦截: {e}")


if __name__ == "__main__":
    asyncio.run(main())
