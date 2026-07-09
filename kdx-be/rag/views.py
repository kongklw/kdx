from rest_framework.views import APIView
from rest_framework import permissions
from rest_framework.response import Response
from pathlib import Path
import os
import sys
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DB_DIR = BASE_DIR / 'data' / 'chroma_db'

_embedding_function = None
_chroma_client = None
_collection = None
_graph = None


def get_embedding_function():
    global _embedding_function
    if _embedding_function is not None:
        return _embedding_function
    sys.path.insert(0, str(BASE_DIR / 'scripts'))
    from text2vec_embedding import Text2VecEmbeddingFunction
    _embedding_function = Text2VecEmbeddingFunction()
    return _embedding_function


def get_chroma_collection():
    global _chroma_client, _collection
    if _collection is not None:
        return _collection
    try:
        from chromadb import PersistentClient
        _chroma_client = PersistentClient(path=str(CHROMA_DB_DIR))
        _collection = _chroma_client.get_collection(
            name="baby_feeding",
            embedding_function=get_embedding_function()
        )
        return _collection
    except Exception as e:
        logger.error(f"Failed to get ChromaDB collection: {e}")
        raise


class RAGState(TypedDict):
    query: str
    documents: dict
    prompt: str
    answer: str
    sources: list


def retrieve_node(state: RAGState) -> RAGState:
    query = state["query"]
    collection = get_chroma_collection()
    results = collection.query(
        query_texts=[query],
        n_results=3
    )
    sources = []
    for meta in results['metadatas'][0]:
        sources.append({
            'title': meta.get('title', ''),
            'filename': meta.get('filename', ''),
            'category': meta.get('category', ''),
            'topics': meta.get('topics', []),
            'age_ranges': meta.get('age_ranges', []),
        })
    return {
        **state,
        "documents": results,
        "sources": sources
    }


def build_prompt(query, documents):
    context = ""
    for i, (doc, meta) in enumerate(zip(documents['documents'][0], documents['metadatas'][0])):
        source = meta.get('filename', '未知来源')
        title = meta.get('title', '')
        context += f"【文档{i+1}】来源: {source}\n标题: {title}\n内容:\n{doc}\n\n"

    system_prompt = """你是一位专业的育儿知识助手。请根据提供的知识库内容，回答用户的问题。

规则：
1. 优先使用知识库中的信息进行回答
2. 如果知识库中没有相关信息，请明确说明"知识库中未找到相关信息"
3. 回答要简洁、准确，避免冗长
4. 可以引用知识库中的来源信息
"""

    prompt = f"{system_prompt}\n\n知识库内容:\n{context}\n\n用户问题: {query}"
    return prompt


def generate_node(state: RAGState) -> RAGState:
    query = state["query"]
    documents = state["documents"]
    prompt = build_prompt(query, documents)
    from langchain_openai import ChatOpenAI
    from kdemo import settings
    model = ChatOpenAI(
        model='qwen3.5-plus',
        api_key=settings.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0,
        streaming=False
    )
    ans = model.invoke(input=prompt)
    if hasattr(ans, 'content'):
        answer = ans.content
    else:
        answer = str(ans)
    return {
        **state,
        "prompt": prompt,
        "answer": answer
    }


def get_rag_graph():
    global _graph
    if _graph is not None:
        return _graph
    from langgraph.graph import StateGraph
    workflow = StateGraph(RAGState)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "generate")
    _graph = workflow.compile()
    return _graph


class RAGQueryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            query = request.data.get('query', '')
            if not query.strip():
                return Response({"code": 400, "msg": "查询内容不能为空", "data": None})

            graph = get_rag_graph()
            result = graph.invoke({"query": query})

            return Response({
                "code": 200,
                "msg": "ok",
                "data": {
                    "answer": result["answer"],
                    "sources": result["sources"],
                    "query": query
                }
            })
        except Exception as e:
            logger.exception(e)
            return Response({"code": 500, "msg": str(e), "data": None})


class CommonView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            from utils.llm_model import llm_chat
            model = llm_chat(model='qwen3.5-plus')
            ans = model.invoke(input="你是谁")
            if hasattr(ans, 'content'):
                answer = ans.content
            else:
                answer = str(ans)
            return Response({"code": 200, "msg": "ok", "data": {"answer": answer}})
        except Exception as e:
            logger.exception(e)
            return Response({"code": 500, "msg": str(e), "data": None})
