"""
Baby Assistant AI 会话服务 (service 层)

封装 LangGraph 助手图 (app/assistant/graph.py) 的执行细节, WS 路由层只做协议分发:
- 运行时上下文注入: set_runtime_context (app/assistant/runtime.py contextvar)
- HITL 写确认: 图 interrupt() 暂停 → confirmation_request 下发 → confirm 恢复
- 遗留 interrupt 清理: 断线残留的挂起写操作, 在新 query 前自动 reject 取消

事件经构造时注入的 emit 回调下发 (WS 无关, 可复用/可测试):
    emit(event_type: str, data: dict)   # 平铺拼接由 WS 层负责
"""

import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from ..assistant.graph import AssistantState, get_compiled_graph
from ..assistant.runtime import reset_runtime_context, set_runtime_context

CONFIRM_TTL_SECONDS = 300     # 挂起写确认有效期 (秒), 超时需重新发起
CANCEL_ANSWER = "好的，已取消本次操作。"


class AssistantSession:
    """单用户会话的图执行封装 (thread_id 绑定多轮记忆 + HITL 状态机)

    thread_id 语义: 同一 thread 每次 ainvoke 只追加新 checkpoint (多轮记忆延续),
    不会自动 resume/time travel; interrupt 恢复仅发生在显式 Command(resume=...) 时,
    由本类 pending_confirm 状态机管理。
    """

    def __init__(self, user_id: int, thread_id: str,
                 emit: Callable[[str, Dict[str, Any]], Awaitable[None]]):
        self.user_id = user_id
        self.thread_id = thread_id
        self._emit = emit
        self._graph = get_compiled_graph()
        self.pending_confirm: Optional[Dict[str, Any]] = None

    # ── 对外入口 (WS 层调用) ─────────────────────────────────

    def _tracked_emit(self):
        """包装 _emit 记录已下发的事件类型, 用于识别 '内容已送达但收尾持久化失败'"""
        seen: set = set()

        async def shim(event_type: str, data: Dict[str, Any]) -> None:
            seen.add(event_type)
            await self._emit(event_type, data)

        return shim, seen

    async def run_query(self, query: str, request_id: str) -> None:
        """执行一次完整 query: 意图识别 → 路由 (agent/rag/chitchat) → 生成, 事件经 emit 下发"""
        # 防御: 上次确认中断线等导致 thread 残留 interrupt → 先自动取消, 保证干净启动
        if self.pending_confirm is None and await self._has_pending_interrupt():
            logger.warning(
                f"[assistant_service] stale interrupt thread={self.thread_id}, auto-cancel")
            await self._resume({"action": "reject"}, request_id=str(uuid.uuid4()),
                               done_route="data_query(stale_cancelled)")

        emit_shim, seen = self._tracked_emit()
        token = set_runtime_context(user_id=self.user_id, request_id=request_id,
                                    emit=emit_shim, thread_id=self.thread_id)
        try:
            result = await self._graph.ainvoke(
                self._initial_state(query, request_id), self._config())
            if await self._handle_interrupt(result, request_id):
                return  # HITL 挂起, 等待 confirm (不发 query_done)
            await self._emit("query_done", self._done_payload(result, request_id))
        except Exception as e:
            logger.exception(f"[assistant_service] query failed thread={self.thread_id}: {e}")
            if seen & {"answer_done", "confirmation_request"}:
                # 内容已送达客户端, 仅收尾持久化失败 (如 checkpointer 写 Redis 超时)
                # → 不能再报 query_error 制造 UX 矛盾, 降级为带标记的 query_done
                await self._emit("query_done", {
                    "request_id": request_id, "route": "degraded",
                    "degraded": True, "note": f"result delivered; final persist failed: {e}",
                })
            else:
                await self._emit("query_error", {"request_id": request_id, "error": str(e)})
        finally:
            reset_runtime_context(token)

    async def resolve_confirm(self, confirm_id: str, action: str) -> None:
        """处理客户端写操作确认, 从 interrupt 暂停点恢复图 (Command 语义)"""
        pending = self.pending_confirm
        if not pending:
            await self._emit("query_error",
                             {"request_id": "", "error": "没有待确认的操作"})
            return
        request_id = pending.get("request_id") or str(uuid.uuid4())
        if confirm_id and pending.get("confirm_id") and confirm_id != pending["confirm_id"]:
            await self._emit("query_error",
                             {"request_id": request_id, "error": "确认ID不匹配"})
            return
        if time.time() - pending.get("ts", time.time()) > CONFIRM_TTL_SECONDS:
            self.pending_confirm = None
            await self._emit("query_error",
                             {"request_id": request_id, "error": "确认已超时，请重新操作"})
            return

        if action == "reject":
            # 先清挂起态 (防并发重复 confirm), 立即反馈取消文案;
            # 再走图内 reject 分支收尾线程, 避免线程停留在 interrupt 态
            self.pending_confirm = None
            await self._emit("generate_chunk", {"request_id": request_id, "chunk": CANCEL_ANSWER})
            await self._emit("answer_done", {"request_id": request_id, "answer": CANCEL_ANSWER})
            await self._resume({"action": "reject"}, request_id,
                               done_route="data_query(rejected)")
            return

        # approve: 从暂停点恢复, 工具执行 + agent 总结由图内完成;
        # 若图内再次 interrupt (多轮写确认), _handle_interrupt 会重建 pending_confirm
        await self._resume({"action": "approve"}, request_id,
                           done_route="data_query(resumed)")

    # ── 内部实现 ─────────────────────────────────────────────

    def _config(self) -> Dict[str, Any]:
        return {"configurable": {"thread_id": self.thread_id}}

    def _initial_state(self, query: str, request_id: str) -> AssistantState:
        # 不传 messages: 由 checkpointer 恢复多轮历史, entry_node 追加当前消息
        return {
            "user_id": self.user_id,
            "query": query,
            "request_id": request_id,
            "tool_trace": [],
            "tool_rounds": 0,
        }

    async def _has_pending_interrupt(self) -> bool:
        """checkpointer 中该 thread 是否有未恢复的 interrupt (断线残留等)"""
        try:
            snapshot = await self._graph.aget_state(self._config())
        except Exception:
            return False
        for task in getattr(snapshot, "tasks", None) or ():
            interrupts = getattr(task, "interrupts", None)
            if callable(interrupts):
                interrupts = interrupts()
            if interrupts:
                return True
        return False

    async def _handle_interrupt(self, result: Any, request_id: str) -> bool:
        """图因 HITL 暂停时: 存挂起态 + 下发 confirmation_request; 返回是否挂起"""
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if not interrupts:
            self.pending_confirm = None
            return False
        first = interrupts[0]
        payload = first if isinstance(first, dict) else getattr(first, "value", first)
        payload = payload or {}
        confirm_id = payload.get("confirm_id") or f"CFM-{uuid.uuid4().hex}"
        self.pending_confirm = {"confirm_id": confirm_id, "request_id": request_id,
                                "ts": time.time()}
        await self._emit("confirmation_request", {
            "request_id": request_id,
            "confirm_id": confirm_id,
            "tools": payload.get("tools", []),
            "message": payload.get("message", "即将写入宝宝数据，请确认"),
            "expires_in": CONFIRM_TTL_SECONDS,
        })
        return True

    async def _resume(self, resume_value: Dict[str, Any], request_id: str,
                      done_route: str) -> None:
        """Command(resume) 恢复图执行; 完成后下发 query_done (再次挂起则重新下发确认)"""
        from langgraph.types import Command  # 懒加载, 与 assistant/graph.py 风格一致

        emit_shim, seen = self._tracked_emit()
        token = set_runtime_context(user_id=self.user_id, request_id=request_id,
                                    emit=emit_shim, thread_id=self.thread_id)
        try:
            result = await self._graph.ainvoke(Command(resume=resume_value), self._config())
            if await self._handle_interrupt(result, request_id):
                return  # 多轮写确认: 重新挂起, 等待下一次 confirm
            await self._emit("query_done", self._done_payload(result, request_id, done_route))
        except Exception as e:
            logger.exception(f"[assistant_service] resume failed thread={self.thread_id}: {e}")
            self.pending_confirm = None
            if seen & {"answer_done", "confirmation_request"}:
                # 同 run_query: 内容已送达, 收尾持久化失败 → 降级 query_done
                await self._emit("query_done", {
                    "request_id": request_id, "route": "degraded", "degraded": True,
                    "note": f"result delivered; final persist failed: {e}",
                })
            else:
                await self._emit("query_error", {"request_id": request_id, "error": str(e)})
        finally:
            reset_runtime_context(token)

    @staticmethod
    def _done_payload(result: Any, request_id: str,
                      route: Optional[str] = None) -> Dict[str, Any]:
        result = result if isinstance(result, dict) else {}
        return {
            "request_id": request_id,
            "intent": result.get("intent"),
            "route": route or result.get("route") or result.get("intent"),
            "tool_trace": result.get("tool_trace") or [],
            "sources": result.get("sources") or [],
        }
