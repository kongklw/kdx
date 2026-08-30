import json
import sys
import os
from uuid import uuid4
from typing import Any, Dict, Optional, AsyncIterator
from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
import asyncio
from loguru import logger

from ..core.config import Settings
from ..core.security import extract_token_from_headers, extract_token_from_cookie, verify_jwt

from typing import TypedDict
# from langchain_openai import ChatOpenAI
# from langchain_core.messages import HumanMessage
# from langgraph.graph import StateGraph

_lc_modules = {}
_lc_initialized = False


def _init_langchain():
    global _lc_initialized, _lc_modules
    if _lc_initialized:
        return _lc_modules

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    from langgraph.graph import StateGraph

    _lc_modules["ChatOpenAI"] = ChatOpenAI
    _lc_modules["HumanMessage"] = HumanMessage
    _lc_modules["StateGraph"] = StateGraph
    _lc_initialized = True
    return _lc_modules


_embedding_function = None
_chroma_client = None
_collection = None


def get_embedding_function():
    global _embedding_function
    if _embedding_function is not None:
        return _embedding_function
    from ..scripts.text2vec_embedding_text2vec import Text2VecEmbeddingFunction
    _embedding_function = Text2VecEmbeddingFunction()
    return _embedding_function


def get_chroma_collection():
    global _chroma_client, _collection
    if _collection is not None:
        return _collection
    try:
        from chromadb import PersistentClient
        chroma_db_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'data', 'chroma_db'
        )
        chroma_db_path = os.path.abspath(chroma_db_path)
        logger.info(f"ChromaDB path: {chroma_db_path}")
        _chroma_client = PersistentClient(path=chroma_db_path)
        _collection = _chroma_client.get_collection(name="baby_feeding")
        logger.info(f"ChromaDB collection count: {_collection.count()}")
        return _collection
    except Exception as e:
        logger.error(f"Failed to get ChromaDB collection: {e}")
        raise


class RAGState(TypedDict):
    query: str
    hits: list          # 混合检索命中 (含融合分/月龄匹配/来源)
    context: str        # 精排 + 父章节扩展后的最终上下文
    documents: dict     # 兼容字段 (原始向量召回结果)
    sources: list
    prompt: str
    answer: str


# 混合检索器单例 (BM25 索引懒构建, 知识库重建后可调 invalidate_index)
_retriever = None


def get_retriever():
    global _retriever
    if _retriever is None:
        from ..rag.retriever import HybridRetriever
        _retriever = HybridRetriever(get_chroma_collection(), get_embedding_function())
    return _retriever


async def send_ws_event(ws: WebSocket, event_type: str, data: Dict[str, Any]):
    await ws.send_json({
        "type": event_type,
        "data": data
    })


def build_context(hits, expanded) -> str:
    """精排 + 父章节扩展后的最终上下文: 命中块全量, 父块标注补充"""
    parts = []
    seen = set()
    for i, item in enumerate(expanded):
        cid = item['id']
        if cid in seen:
            continue
        seen.add(cid)
        meta = item.get('meta') or {}
        title = meta.get('title') or meta.get('section') or '未知来源'
        tag = '命中' if item.get('rel') == 'hit' else '补充'
        parts.append(f"【文档{i + 1}·{tag}】标题: {title}\n内容:\n{item['doc']}")
    return '\n\n'.join(parts)


def build_prompt(query, context):
    system_prompt = """你是一位专业的育儿知识助手。请根据提供的知识库内容，回答用户的问题。

规则：
1. 优先使用知识库中的信息进行回答
2. 如果知识库中没有相关信息，请明确说明"知识库中未找到相关信息"
3. 回答要简洁、准确，避免冗长
4. 回答时标注引用来源，如 [文档1]
"""

    return f"{system_prompt}\n\n知识库内容:\n{context}\n\n用户问题: {query}"


async def retrieve_node(state: RAGState, ws: WebSocket) -> RAGState:
    """混合检索: 向量 + BM25 RRF 融合, 月龄软过滤, 权威度加权"""
    query = state["query"]
    await send_ws_event(ws, "retrieve_start", {"query": query})

    retriever = get_retriever()
    result = retriever.search(query, k=3, fetch=20)
    hits = result['hits']

    await send_ws_event(ws, "retrieve_done", {
        "query": query,
        "count": len(hits),
        "age_months": result['age_months'],
        "debug": result['debug'],
        "documents": [{
            'index': i + 1,
            'id': h['id'],
            'title': (h.get('meta') or {}).get('title', ''),
            'section': (h.get('meta') or {}).get('section', ''),
            'category': (h.get('meta') or {}).get('category', ''),
            'score': round(h['score'], 4),
            'vec_rank': h.get('vec_rank'),
            'bm25_rank': h.get('bm25_rank'),
            'age_match': h.get('age_match'),
        } for i, h in enumerate(hits)],
    })

    return {**state,
            "hits": hits,
            "sources": [{
                'index': i + 1,
                'title': (h.get('meta') or {}).get('title', ''),
                'filename': (h.get('meta') or {}).get('filename', ''),
                'category': (h.get('meta') or {}).get('category', ''),
            } for i, h in enumerate(hits)],
            }


async def rerank_node(state: RAGState, ws: WebSocket) -> RAGState:
    """父章节扩展 (small-to-big): 命中块 → 同父章节相邻块, 组装最终上下文"""
    hits = state["hits"]

    retriever = get_retriever()
    expanded = retriever.expand_parents(hits)
    context = build_context(hits, expanded)

    await send_ws_event(ws, "rerank_done", {
        "hit_count": len(hits),
        "expanded_count": len(expanded),
        "context_chars": len(context),
    })

    return {**state, "context": context}


async def generate_node(state: RAGState, ws: WebSocket) -> RAGState:
    print(f'generate_node')
    query = state["query"]
    context = state["context"]

    await send_ws_event(ws, "generate_start", {"query": query})

    prompt = build_prompt(query, context)
    await send_ws_event(ws, "prompt_generated", {
        "prompt_length": len(prompt)
    })

    lc = _init_langchain()
    ChatOpenAI = lc["ChatOpenAI"]
    HumanMessage = lc["HumanMessage"]

    api_key = os.getenv("DASHSCOPE_API_KEY")
    model = ChatOpenAI(
        model='qwen3.7-plus',
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0,
        streaming=True
    )

    full_answer = ""
    async for chunk in model.astream([HumanMessage(content=prompt)]):
        if chunk.content:
            full_answer += chunk.content
            await send_ws_event(ws, "generate_chunk", {
                "chunk": chunk.content,
                "total_length": len(full_answer)
            })

    await send_ws_event(ws, "generate_done", {
        "answer": full_answer,
        "sources": state["sources"]
    })

    return {
        **state,
        "prompt": prompt,
        "answer": full_answer
    }


def create_rag_graph(ws: WebSocket):
    logger.info(f"before init lc")
    lc = _init_langchain()
    logger.info(f"already init lc")

    StateGraph = lc["StateGraph"]
    workflow = StateGraph(RAGState)

    async def retrieve_with_ws(state: RAGState) -> RAGState:
        return await retrieve_node(state, ws)

    async def rerank_with_ws(state: RAGState) -> RAGState:
        return await rerank_node(state, ws)

    async def generate_with_ws(state: RAGState) -> RAGState:
        return await generate_node(state, ws)

    workflow.add_node("retrieve", retrieve_with_ws)
    workflow.add_node("rerank", rerank_with_ws)
    workflow.add_node("generate", generate_with_ws)
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "rerank")
    workflow.add_edge("rerank", "generate")

    return workflow.compile()


async def rag_query_websocket(
        ws: WebSocket,
        settings: Settings,
) -> None:
    user: Optional[Dict[str, Any]] = None

    token: Optional[str] = None
    token = ws.query_params.get("token")
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

    async def receive_messages():
        while True:
            message = await ws.receive()
            msg_type = message.get("type")
            text = message.get("text")
            print(f'text -> {text}')

            if msg_type == "websocket.disconnect":
                break
            if msg_type != "websocket.receive":
                continue

            if text is None:
                continue

            try:
                payload = json.loads(text)
                if payload.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
                    continue
                if payload.get("type") == "query":
                    query = payload.get("query", "")
                    print(f'query -> {query}')
                    if query:
                        await process_query(query)
            except Exception as e:
                logger.error(f"Failed to parse message: {e}")

    async def process_query(query: str):
        logger.info(f"[STEP 1] Before send_ws_event")
        await send_ws_event(ws, "query_start", {"query": query})

        try:
            logger.info(f"[STEP 2] After send_ws_event, before create_rag_graph")
            graph = create_rag_graph(ws)
            logger.info(f"[STEP 3] After create_rag_graph")
            result = await graph.ainvoke({"query": query})
            logger.info(f"[STEP 4] After graph.ainvoke")

            await send_ws_event(ws, "query_done", {
                "query": query,
                "answer": result["answer"],
                "sources": result["sources"]
            })
        except Exception as e:
            logger.exception(f"RAG query failed: {e}")
            await send_ws_event(ws, "query_error", {
                "error": str(e)
            })

    try:
        await receive_messages()
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("rag_query_websocket unhandled exception")
        try:
            await ws.close(code=1011, reason="internal error")
        except Exception:
            return


def create_rag_query_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/rag_query")
    async def on_connect(ws: WebSocket) -> None:
        await rag_query_websocket(ws, settings)

    return router
