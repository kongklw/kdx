"""
Agent 运行时上下文 (全局共享图的前提)
======================================

通过 contextvar 在运行时注入连接级上下文 (emit 回调/用户身份),
使图可以在进程启动时编译一次、全局共享, 不再 per-connection 编图。

用法:
    token = set_runtime_context(user_id=..., request_id=..., emit=...)
    try:
        result = await graph.ainvoke(state, config)
    finally:
        reset_runtime_context(token)
"""

import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger


# ──────────────────────────────────────────────
# 运行时上下文
# ──────────────────────────────────────────────

@dataclass
class RuntimeContext:
    """节点内可获取的运行时上下文 (每次请求注入)"""
    user_id: int = 0
    request_id: str = ""
    emit: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
    thread_id: str = ""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))


_ctx_var: ContextVar[RuntimeContext] = ContextVar(
    "agent_runtime_ctx", default=RuntimeContext()
)


def set_runtime_context(
    user_id: int,
    request_id: str,
    emit: Optional[Callable] = None,
    thread_id: str = "",
) -> Token:
    """WS 层进入图执行前调用, 返回 token 用于恢复"""
    return _ctx_var.set(RuntimeContext(
        user_id=user_id,
        request_id=request_id,
        emit=emit,
        thread_id=thread_id,
    ))


def reset_runtime_context(token: Token) -> None:
    _ctx_var.reset(token)


def get_runtime_context() -> RuntimeContext:
    """节点内调用, 获取当前请求的上下文"""
    return _ctx_var.get()


async def emit(event_type: str, data: Dict[str, Any]) -> None:
    """节点内推送 WS 事件 (通过 contextvar 获取 emit 回调)"""
    ctx = _ctx_var.get()
    if ctx.emit is None:
        return
    try:
        await ctx.emit(event_type, data)
    except Exception as e:
        logger.warning(f"emit failed: {event_type} - {e}")
