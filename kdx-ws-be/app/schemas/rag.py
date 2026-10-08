"""rag HTTP 兼容桥接请求 schema"""
from pydantic import BaseModel


class RagQueryRequest(BaseModel):
    """POST /rag/query/ 请求体 (兼容老 Django: {"query": "..."})"""
    query: str = ""
