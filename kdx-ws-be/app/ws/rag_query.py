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

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph
from typing import TypedDict

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
    documents: dict
    sources: list
    prompt: str
    answer: str


async def send_ws_event(ws: WebSocket, event_type: str, data: Dict[str, Any]):
    await ws.send_json({
        "type": event_type,
        "data": data
    })


def build_prompt(query, documents):
    context = ""
    for i, (doc, meta) in enumerate(zip(documents['documents'][0], documents['metadatas'][0])):
        source = meta.get('filename', '未知来源')
        title = meta.get('title', '')
        context += f"【文档{i + 1}】来源: {source}\n标题: {title}\n内容:\n{doc}\n\n"

    system_prompt = """你是一位专业的育儿知识助手。请根据提供的知识库内容，回答用户的问题。

规则：
1. 优先使用知识库中的信息进行回答
2. 如果知识库中没有相关信息，请明确说明"知识库中未找到相关信息"
3. 回答要简洁、准确，避免冗长
4. 可以引用知识库中的来源信息
"""

    prompt = f"{system_prompt}\n\n知识库内容:\n{context}\n\n用户问题: {query}"
    return prompt


async def retrieve_node(state: RAGState, ws: WebSocket) -> RAGState:
    print(f'retrieve node -> {state}')
    query = state["query"]
    await send_ws_event(ws, "retrieve_start", {"query": query})

    collection = get_chroma_collection()
    query_embedding = get_embedding_function().embed_query(query)
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=3
    )

    sources = []
    docs_info = []
    for i, meta in enumerate(results['metadatas'][0]):
        source_info = {
            'index': i + 1,
            'title': meta.get('title', ''),
            'filename': meta.get('filename', ''),
            'category': meta.get('category', ''),
            'topics': meta.get('topics', []),
            'age_ranges': meta.get('age_ranges', []),
        }
        sources.append(source_info)
        docs_info.append({
            **source_info,
            'content': results['documents'][0][i][:200] + '...' if len(results['documents'][0][i]) > 200 else
            results['documents'][0][i],
            'distance': float(results['distances'][0][i]) if results.get('distances') else None
        })

    await send_ws_event(ws, "retrieve_done", {
        "query": query,
        "count": len(docs_info),
        "documents": docs_info
    })

    return {
        **state,
        "documents": results,
        "sources": sources
    }


async def generate_node(state: RAGState, ws: WebSocket) -> RAGState:
    print(f'generate_node {state}')
    query = state["query"]
    documents = state["documents"]

    await send_ws_event(ws, "generate_start", {"query": query})

    prompt = build_prompt(query, documents)
    await send_ws_event(ws, "prompt_generated", {
        "prompt_length": len(prompt)
    })

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
    workflow = StateGraph(RAGState)

    async def retrieve_with_ws(state: RAGState) -> RAGState:
        return await retrieve_node(state, ws)

    async def generate_with_ws(state: RAGState) -> RAGState:
        return await generate_node(state, ws)

    workflow.add_node("retrieve", retrieve_with_ws)
    workflow.add_node("generate", generate_with_ws)
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "generate")

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
        await send_ws_event(ws, "query_start", {"query": query})

        try:
            graph = create_rag_graph(ws)
            result = await graph.ainvoke({"query": query})

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
