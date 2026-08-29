"""
Baby Assistant WebSocket 路由

协议 (与现有 rag_query / voice_agent 一致的 {type, data} 事件格式):

Client → Server:
  {"type": "ping"}
  {"type": "query", "query": "今天喝了多少奶", "request_id": "uuid"}
  {"type": "confirm", "confirm_id": "CFM-...", "action": "approve" | "reject"}

Server → Client:
  {"type": "connected", ...}
  {"type": "pong"}
  {"type": "intent_start" | "intent_detected" | "retrieve_start" | "retrieve_done"}
  {"type": "tool_call", "id", "name", "args"}
  {"type": "tool_result", "id", "name", "result", "ok"}
  {"type": "confirmation_request", "confirm_id", "tools", "message"}
  {"type": "generate_chunk", "chunk"}
  {"type": "answer_done", "answer", ...}
  {"type": "query_done", "request_id", "route", "tool_trace"}
  {"type": "query_error", "error"}

鉴权 (example/auth.py 三种提取方式落地):
  query 参数 token / Authorization: Bearer / Cookie
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
from loguru import logger

from ..core.config import Settings
from ..core.security import extract_token_from_headers, extract_token_from_cookie, verify_jwt
from ..assistant.graph import build_assistant_graph, make_resume_state, AssistantState
from ..assistant.resilience import IdempotencyManager

MAX_HISTORY_MESSAGES = 20  # 连接内多轮上下文上限


def create_baby_assistant_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/baby_assistant")
    async def on_connect(ws: WebSocket) -> None:
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
        await ws.accept()
        await ws.send_json({
            "type": "connected",
            "user_id": user_id,
            "message": "baby assistant ready",
        })

        # ── 连接级会话状态 (状态机管理落地) ──────────────────
        # session_states: idle → processing → wait_confirm → idle
        graph = build_assistant_graph(ws=ws)
        idem = IdempotencyManager()
        history: List[Any] = []            # 跨轮对话记忆 (langchain messages)
        pending: Optional[Dict[str, Any]] = None   # HITL 挂起的确认上下文
        processing = False                 # 防止并发 query 打乱状态

        async def send_event(event_type: str, data: Dict[str, Any]):
            try:
                await ws.send_json({"type": event_type, "data": data})
            except Exception:
                pass

        def build_initial_state(query: str, request_id: str) -> AssistantState:
            return {
                "user_id": user_id,
                "query": query,
                "request_id": request_id,
                "resume": False,
                "messages": list(history),
                "tool_trace": [],
                "tool_rounds": 0,
            }

        async def process_query(query: str, request_id: str):
            """正常查询流程: invoke graph → 可能产生 HITL 挂起"""
            nonlocal history, pending
            await send_event("query_start", {"query": query, "request_id": request_id})
            try:
                result = await graph.ainvoke(build_initial_state(query, request_id))

                # 多轮记忆: 保留 query + 最终回答
                from langchain_core.messages import HumanMessage, AIMessage
                history = history + [HumanMessage(content=query)]
                if result.get("answer"):
                    history = history + [AIMessage(content=result["answer"])]
                history = history[-MAX_HISTORY_MESSAGES:]

                # HITL 挂起: 等待用户 confirm
                if result.get("pending_write"):
                    pending = dict(result)
                    await send_event("wait_confirm", {
                        "confirm_id": result["pending_write"]["confirm_id"],
                        "hint": "发送 {type:'confirm', action:'approve'/'reject'} 继续",
                    })
                else:
                    pending = None

                await send_event("query_done", {
                    "request_id": request_id,
                    "intent": result.get("intent"),
                    "route": result.get("route") or result.get("intent"),
                    "tool_trace": result.get("tool_trace") or [],
                })
            except Exception as e:
                logger.exception(f"[baby_assistant] query failed: {e}")
                await send_event("query_error", {"error": str(e)})

        async def process_confirm(confirm_id: str, action: str):
            """HITL 确认/拒绝流程 (example/hitl.py 的 interrupt→Command(resume) 落地)"""
            nonlocal pending, history
            if not pending:
                await send_event("query_error", {"error": "no pending confirmation"})
                return
            stored_confirm_id = (pending.get("pending_write") or {}).get("confirm_id")
            if confirm_id and stored_confirm_id and confirm_id != stored_confirm_id:
                await send_event("query_error", {"error": "confirm_id mismatch"})
                return

            if action == "reject":
                # 拒绝: 直接取消, 不重新进图 (避免 Agent 再次发起写操作循环)
                await send_event("generate_chunk", {"chunk": "好的，已取消本次操作。"})
                await send_event("answer_done", {"answer": "好的，已取消本次操作。"})
                pending = None
                return

            # approve: 从暂停点恢复执行
            resume_state = make_resume_state(pending, confirmed=True)
            try:
                result = await graph.ainvoke(resume_state)
                from langchain_core.messages import AIMessage
                if result.get("answer"):
                    history = history + [AIMessage(content=result["answer"])]
                    history = history[-MAX_HISTORY_MESSAGES:]
                await send_event("query_done", {
                    "request_id": pending.get("request_id"),
                    "intent": result.get("intent"),
                    "route": "data_query(resume)",
                    "tool_trace": result.get("tool_trace") or [],
                })
            except Exception as e:
                logger.exception(f"[baby_assistant] resume failed: {e}")
                await send_event("query_error", {"error": str(e)})
            finally:
                pending = None

        # ── 消息循环 ─────────────────────────────────────────
        try:
            while True:
                message = await ws.receive()
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

    return router
