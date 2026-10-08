"""
Baby Assistant WebSocket 路由 (生产版)

协议 (与 rag_query 一致的 {type, data} 事件格式):

Client → Server:
  {"type": "ping"}
  {"type": "query", "query": "...", "request_id": "uuid"}
  {"type": "confirm", "confirm_id": "CFM-...", "action": "approve" | "reject"}

Server → Client:
  {"type": "connected", ...}
  {"type": "pong"}
  {"type": "query_start", ...}
  {"type": "intent_start" | "intent_detected" | "retrieve_start" | "retrieve_done"}
  {"type": "tool_call", "id", "name", "args"}
  {"type": "tool_result", "id", "name", "result", "ok"}
  {"type": "confirmation_request", "confirm_id", "tools", "message"}
  {"type": "generate_chunk", "chunk"}
  {"type": "answer_done", "answer", ...}
  {"type": "query_done", "request_id", "route", "tool_trace"}
  {"type": "query_error", "error"}

生产化重构要点 (vs 旧版):
- 全局共享图: get_compiled_graph() 进程级编译一次, 不再 per-connection 编图
- 会话持久化: thread_id = user-{user_id}, checkpointer 承载多轮记忆 (断线可恢复)
- contextvar: set_runtime_context 注入 emit/身份, 节点不再闭包捕获 ws
- 原生 HITL: interrupt() 暂停 → Command(resume=...) 恢复, 确认元数据存 Redis(TTL 5min)
- 限流: Redis 滑动窗口 30 次/分钟/用户 (降级内存)
- 输入限长: query ≤ 500 字符 (防 prompt 费用攻击)
- 空闲踢出: 10 分钟无消息自动断开 (防半开连接占资源)

鉴权 (example/auth.py 三种提取方式落地):
  query 参数 token / Authorization: Bearer / Cookie
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
from loguru import logger

from ..core.config import Settings
from ..core.security import extract_token_from_headers, extract_token_from_cookie, verify_jwt

MAX_QUERY_LEN = 500           # 输入限长
RATE_LIMIT_CALLS = 30         # 每用户每分钟查询上限
CONFIRM_TTL = 300             # 挂起写操作确认过期时间 (秒)
IDLE_TIMEOUT = 600            # 空闲连接踢出 (秒)


def create_baby_assistant_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/baby_assistant")
    async def on_connect(ws: WebSocket) -> None:
        await baby_assistant_websocket(ws, settings)

    return router


async def baby_assistant_websocket(ws: WebSocket, settings: Settings) -> None:
    # ── 鉴权 (JWT, 三种 token 提取方式) ──────────────────
    token: Optional[str] = ws.query_params.get("token")
    if not token:
        token = extract_token_from_headers(ws.headers.get("authorization"))
    if not token:
        token = extract_token_from_cookie(ws.headers.get("cookie"))

    if not token:
        await ws.close(code=4401, reason="missing token")
        logger.warning("[baby_assistant] rejected: no token")
        return

    try:
        user = verify_jwt(token, settings)
    except Exception as e:
        await ws.close(code=4401, reason=f"invalid token: {e}")
        logger.warning(f"[baby_assistant] rejected: invalid token - {e}")
        return

    user_id = int(user.get("user_id"))
    thread_id = f"user-{user_id}"   # 会话持久化键 (checkpointer 跨连接延续记忆)
    await ws.accept()
    await ws.send_json({
        "type": "connected",
        "user_id": user_id,
        "message": "baby assistant ready (protocol v2)",
    })

    # ── 全局共享图 (进程级编译一次, 带 checkpointer) ──────
    from ..assistant.graph import get_compiled_graph, AssistantState
    from ..assistant.runtime import set_runtime_context, reset_runtime_context
    from ..assistant.resilience import RateLimiter
    from langgraph.types import Command

    graph = get_compiled_graph()
    limiter = RateLimiter(redis_url=settings.redis_url,
                          max_calls=RATE_LIMIT_CALLS, window_seconds=60)
    pending_redis = None            # 懒加载 Redis (跨连接恢复挂起确认)
    processing = False              # 防止并发 query 打乱状态机

    async def send_event(event_type: str, data: Dict[str, Any]):
        try:
            await ws.send_json({"type": event_type, "data": data})
        except Exception:
            pass

    async def get_redis():
        nonlocal pending_redis
        if pending_redis is not None:
            return pending_redis if pending_redis is not False else None
        try:
            import redis.asyncio as aioredis
            pending_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await pending_redis.ping()
        except Exception:
            pending_redis = False
        return pending_redis if pending_redis is not False else None

    def build_initial_state(query: str, request_id: str) -> AssistantState:
        # 不传 messages: 由 checkpointer 恢复历史, entry_node 追加当前用户消息
        return {
            "user_id": user_id,
            "query": query,
            "request_id": request_id,
            "tool_trace": [],
            "tool_rounds": 0,
        }

    def graph_config() -> Dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    async def store_pending(confirm_id: str, request_id: str) -> None:
        payload = json.dumps({"confirm_id": confirm_id, "request_id": request_id,
                              "ts": time.time()}, ensure_ascii=False)
        r = await get_redis()
        if r:
            try:
                await r.set(f"agent:pending:{thread_id}", payload, ex=CONFIRM_TTL)
                return
            except Exception:
                pass

    async def load_pending() -> Optional[Dict[str, Any]]:
        r = await get_redis()
        if r:
            try:
                raw = await r.get(f"agent:pending:{thread_id}")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return None

    async def clear_pending() -> None:
        r = await get_redis()
        if r:
            try:
                await r.delete(f"agent:pending:{thread_id}")
            except Exception:
                pass

    async def handle_interrupt(result: Dict[str, Any], request_id: str) -> None:
        """图因 HITL 暂停: 提取 interrupt 载荷, 下发确认请求"""
        interrupts = result.get("__interrupt__")
        if not interrupts:
            return
        first = interrupts[0]
        payload = getattr(first, "value", first) if not isinstance(first, dict) else first
        confirm_id = payload.get("confirm_id") or f"CFM-{uuid.uuid4().hex}"
        await store_pending(confirm_id, request_id)
        await send_event("confirmation_request", {
            "request_id": request_id,
            "confirm_id": confirm_id,
            "tools": payload.get("tools", []),
            "message": payload.get("message", "即将写入宝宝数据，请确认"),
            "expires_in": CONFIRM_TTL,
        })

    async def run_graph(state: AssistantState, request_id: str) -> Dict[str, Any]:
        """统一执行入口: 注入运行时上下文 → 图执行 → 处理 HITL 挂起"""
        token = set_runtime_context(user_id=user_id, request_id=request_id,
                                    emit=send_event, thread_id=thread_id)
        try:
            result = await graph.ainvoke(state, graph_config())
            await handle_interrupt(result, request_id)
            return result
        finally:
            reset_runtime_context(token)

    async def process_query(query: str, request_id: str) -> None:
        await send_event("query_start", {"query": query, "request_id": request_id})
        try:
            result = await run_graph(build_initial_state(query, request_id), request_id)

            # HITL 挂起时不再发 query_done (等待 confirm)
            if result.get("__interrupt__"):
                return

            await send_event("query_done", {
                "request_id": request_id,
                "intent": result.get("intent"),
                "route": result.get("route") or result.get("intent"),
                "tool_trace": result.get("tool_trace") or [],
                "sources": result.get("sources") or [],
            })
        except Exception as e:
            logger.exception(f"[baby_assistant] query failed: {e}")
            await send_event("query_error", {"error": str(e)})

    async def process_confirm(confirm_id: str, action: str) -> None:
        pending = await load_pending()
        if not pending:
            await send_event("query_error", {"error": "no pending confirmation or expired"})
            return
        if pending.get("confirm_id") and confirm_id and confirm_id != pending["confirm_id"]:
            await send_event("query_error", {"error": "confirm_id mismatch"})
            return
        # 过期检查 (Redis 已按 TTL 过期; 内存态兜底)
        if time.time() - pending.get("ts", time.time()) > CONFIRM_TTL:
            await clear_pending()
            await send_event("query_error", {"error": "confirmation expired, please retry"})
            return

        if action == "reject":
            await clear_pending()
            # 拒绝: 直接取消, 不重新进图 (避免 Agent 再次发起写操作循环)
            await send_event("generate_chunk", {"chunk": "好的，已取消本次操作。"})
            await send_event("answer_done", {"answer": "好的，已取消本次操作。"})
            await send_event("query_done", {
                "request_id": pending.get("request_id", ""),
                "intent": "data_query",
                "route": "data_query(rejected)",
                "tool_trace": [],
            })
            return

        # approve: 从 interrupt 暂停点恢复 (Command(resume) 语义)
        request_id = pending.get("request_id") or str(uuid.uuid4())
        token = set_runtime_context(user_id=user_id, request_id=request_id,
                                    emit=send_event, thread_id=thread_id)
        try:
            result = await graph.ainvoke(
                Command(resume={"action": "approve"}), graph_config())
            # 多轮挂起: 图内再次 interrupt (如多工具链) → 重新下发确认
            await handle_interrupt(result, request_id)
            if result.get("__interrupt__"):
                return
            await send_event("query_done", {
                "request_id": request_id,
                "intent": result.get("intent") or "data_query",
                "route": "data_query(resumed)",
                "tool_trace": result.get("tool_trace") or [],
                "sources": result.get("sources") or [],
            })
        except Exception as e:
            logger.exception(f"[baby_assistant] resume failed: {e}")
            await send_event("query_error", {"error": str(e)})
        finally:
            await clear_pending()
            reset_runtime_context(token)

    # ── 消息循环 ─────────────────────────────────────────
    try:
        while True:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                await ws.close(code=1001, reason="idle timeout")
                return
            msg_type = message.get("type")

            if msg_type == "websocket.disconnect":
                break
            if msg_type != "websocket.receive":
                continue
            text = message.get("text")
            if not text:
                continue

            try:
                payload = json.loads(text)
            except Exception as e:
                await send_event("query_error", {"error": f"invalid json: {e}"})
                continue

            p_type = payload.get("type")
            if p_type == "ping":
                await send_event("pong", {})
                continue

            if p_type == "query":
                query = (payload.get("query") or "").strip()
                if not query:
                    continue
                if len(query) > MAX_QUERY_LEN:
                    await send_event("query_error", {
                        "error": f"query too long (max {MAX_QUERY_LEN} chars)"})
                    continue
                if not await limiter.allow(f"user:{user_id}"):
                    await send_event("query_error", {
                        "error": f"rate limit exceeded ({RATE_LIMIT_CALLS}/min)"})
                    continue
                if await load_pending():
                    await send_event("query_error", {
                        "error": "有待确认的操作未处理，请先确认或取消"})
                    continue
                if processing:
                    await send_event("query_error", {"error": "busy: previous query in progress"})
                    continue
                processing = True
                try:
                    request_id = payload.get("request_id") or str(uuid.uuid4())
                    await process_query(query, request_id)
                finally:
                    processing = False
                continue

            if p_type == "confirm":
                if processing:
                    await send_event("query_error", {"error": "busy"})
                    continue
                processing = True
                try:
                    await process_confirm(
                        payload.get("confirm_id") or "",
                        payload.get("action") or "reject",
                    )
                finally:
                    processing = False
                continue

            await send_event("query_error", {"error": f"unknown type: {p_type}"})

    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("[baby_assistant] unhandled exception")
        try:
            await ws.close(code=1011, reason="internal error")
        except Exception:
            return
