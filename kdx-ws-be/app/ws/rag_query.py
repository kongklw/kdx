"""
独立 RAG 查询 WebSocket 端点 (生产版)

重构要点 (vs 旧版):
- 单例下沉: collection/embedding/retriever 不再在本文件, 统一走 app.rag.service
- 统一检索: 用 RetrievalService (混合检索 + 精排 + 多轮改写 + 预算裁剪), 不再自建 graph
- LLM 网关: 生成走 llm_gateway (熔断/降级/计量), 不再硬编码 ChatOpenAI
- to_thread: 所有同步 IO (检索/embedding) 在 RetrievalService 内已包裹, 不阻塞事件循环
- 输入限长: 防超长 prompt 注入
"""

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
from loguru import logger

from ..core.config import Settings
from ..core.security import extract_token_from_headers, extract_token_from_cookie, verify_jwt

MAX_QUERY_LEN = 500   # 输入限长 (防 prompt 注入)


async def send_ws_event(ws: WebSocket, event_type: str, data: Dict[str, Any]):
    await ws.send_json({"type": event_type, "data": data})


async def rag_query_websocket(
        ws: WebSocket,
        settings: Settings,
) -> None:
    # ── 鉴权 (JWT, 三种 token 提取方式) ──────────────────
    token: Optional[str] = ws.query_params.get("token")
    if not token:
        token = extract_token_from_headers(ws.headers.get("authorization"))
    if not token:
        token = extract_token_from_cookie(ws.headers.get("cookie"))

    if not token:
        await ws.close(code=4401, reason="missing token: token is required for WebSocket connection")
        logger.warning("WebSocket connection rejected: no token provided")
        return

    try:
        user = verify_jwt(token, settings)
        logger.info(f"WebSocket authenticated user: {user.get('user_id')}")
    except Exception as e:
        await ws.close(code=4401, reason=f"invalid token: {str(e)}")
        logger.warning(f"WebSocket connection rejected: invalid token - {str(e)}")
        return

    await ws.accept()
    await ws.send_json({
        "type": "connected",
        "user_id": (user or {}).get("user_id"),
        "message": "RAG query websocket ready"
    })

    # ── 消息循环 ─────────────────────────────────────────
    try:
        while True:
            message = await ws.receive()
            msg_type = message.get("type")
            text = message.get("text")

            if msg_type == "websocket.disconnect":
                break
            if msg_type != "websocket.receive":
                continue
            if text is None:
                continue

            try:
                payload = json.loads(text)
            except Exception as e:
                await send_ws_event(ws, "query_error", {"error": f"invalid json: {e}"})
                continue

            p_type = payload.get("type")

            if p_type == "ping":
                await ws.send_json({"type": "pong"})
                continue

            if p_type == "query":
                query = (payload.get("query") or "").strip()
                if not query:
                    continue
                if len(query) > MAX_QUERY_LEN:
                    await send_ws_event(ws, "query_error", {
                        "error": f"query too long (max {MAX_QUERY_LEN} chars)"
                    })
                    continue
                await process_rag_query(ws, query)
                continue

            await send_ws_event(ws, "query_error", {"error": f"unknown type: {p_type}"})

    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("rag_query_websocket unhandled exception")
        try:
            await ws.close(code=1011, reason="internal error")
        except Exception:
            return


async def process_rag_query(ws: WebSocket, query: str):
    """RAG 查询: RetrievalService 检索 → llm_gateway 流式生成"""
    await send_ws_event(ws, "query_start", {"query": query})

    try:
        # ── ① 统一检索 (混合检索 + 精排 + 父章节扩展 + 预算裁剪) ──
        from ..rag.service import RetrievalRequest, get_retrieval_service
        from ..assistant.llm_gateway import get_llm_gateway
        from ..assistant.resilience import CircuitOpenError
        from langchain_core.messages import HumanMessage, SystemMessage

        await send_ws_event(ws, "retrieve_start", {"query": query})

        svc = get_retrieval_service()
        req = RetrievalRequest(query=query, top_k=3, fetch=20, enable_rerank=True)
        result = await svc.search(req)

        await send_ws_event(ws, "retrieve_done", {
            "count": len(result.hits),
            "sources": [{"index": s.index, "title": s.title,
                         "filename": s.filename, "category": s.category}
                        for s in result.sources],
            "debug": result.debug,
        })

        # ── ② 流式生成 (走 LLM 网关: 熔断 + 降级) ──────────────
        context = result.context or "(知识库未返回内容)"
        system = SystemMessage(content=(
            "你是一位专业的育儿知识助手。请根据提供的知识库内容，回答用户的问题。\n\n"
            "规则:\n"
            "1. 优先使用知识库中的信息进行回答\n"
            "2. 如果知识库中没有相关信息，请明确说明\"知识库中未找到相关信息\"\n"
            "3. 回答要简洁、准确，避免冗长\n"
            "4. 回答时标注引用来源，如 [文档1]\n\n"
            f"知识库内容:\n{context}"
        ))

        await send_ws_event(ws, "generate_start", {"query": query})

        gw = get_llm_gateway()
        full_answer = ""
        try:
            async for chunk in gw.astream("rag", [system, HumanMessage(content=query)]):
                if chunk.content:
                    full_answer += chunk.content
                    await send_ws_event(ws, "generate_chunk", {
                        "chunk": chunk.content,
                        "total_length": len(full_answer),
                    })
        except CircuitOpenError:
            full_answer = "【系统降级】AI 服务暂时不可用，请稍后重试。"
            await send_ws_event(ws, "generate_chunk", {"chunk": full_answer})

        await send_ws_event(ws, "generate_done", {
            "answer": full_answer,
            "sources": [{"index": s.index, "title": s.title,
                         "filename": s.filename, "category": s.category}
                        for s in result.sources],
        })

        await send_ws_event(ws, "query_done", {
            "query": query,
            "answer": full_answer,
            "sources": [{"index": s.index, "title": s.title,
                         "filename": s.filename, "category": s.category}
                        for s in result.sources],
        })

    except Exception as e:
        logger.exception(f"RAG query failed: {e}")
        await send_ws_event(ws, "query_error", {"error": str(e)})


def create_rag_query_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/rag_query")
    async def on_connect(ws: WebSocket) -> None:
        await rag_query_websocket(ws, settings)

    return router
