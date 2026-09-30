"""
检索服务门面 (RetrievalService)
==============================

统一检索入口: Agent 图内 RAG 节点、/ws/rag_query 端点、未来 HTTP API
全部走这里，消除"两条 RAG 链路不一致"的分层倒挂问题。

单例 (collection / embed_fn / retriever / bm25) 从 ws/rag_query.py 下沉到本包，
assistant 不再反向依赖 ws 层。
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

@dataclass
class Hit:
    id: str
    doc: str
    meta: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    vec_rank: Optional[int] = None
    bm25_rank: Optional[int] = None
    age_match: Optional[bool] = None
    rel: str = "hit"  # 'hit' | 'parent'


@dataclass
class Source:
    index: int
    title: str = ""
    filename: str = ""
    category: str = ""
    section: str = ""


@dataclass
class RetrievalRequest:
    query: str
    top_k: int = 3
    fetch: int = 20
    age_months: Optional[float] = None       # Agent 侧可显式传入
    history: Optional[List[str]] = None      # 多轮改写用
    enable_rerank: bool = True


@dataclass
class RetrievalResult:
    hits: List[Hit]
    expanded: List[Hit]
    context: str
    sources: List[Source]
    debug: Dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────
# 单例管理 (进程级, 懒加载)
# ──────────────────────────────────────────────

_embedding_function = None
_chroma_client = None
_collection = None
_retriever = None


def get_embedding_function():
    """获取 embedding 函数单例 (可切换 text2vec / TEI 服务)"""
    global _embedding_function
    if _embedding_function is not None:
        return _embedding_function

    # 优先使用 TEI 服务 (环境变量配置时)
    tei_url = os.getenv("TEI_EMBEDDING_URL", "")
    if tei_url:
        from .embed_client import TEIEmbeddingFunction
        _embedding_function = TEIEmbeddingFunction(base_url=tei_url)
        logger.info(f"Using TEI embedding service: {tei_url}")
        return _embedding_function

    # 回退: 本地 text2vec (现有实现)
    from ..scripts.text2vec_embedding_text2vec import Text2VecEmbeddingFunction
    _embedding_function = Text2VecEmbeddingFunction()
    logger.info("Using local text2vec-base-chinese embedding")
    return _embedding_function


def get_chroma_collection():
    """获取 ChromaDB collection 单例"""
    global _chroma_client, _collection
    if _collection is not None:
        return _collection
    try:
        from chromadb import PersistentClient
        chroma_db_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'data', 'chroma_db'
        )
        chroma_db_path = os.path.abspath(chroma_db_path)
        _chroma_client = PersistentClient(path=chroma_db_path)
        _collection = _chroma_client.get_collection(name="baby_feeding")
        logger.info(f"ChromaDB collection count: {_collection.count()}")
        return _collection
    except Exception as e:
        logger.error(f"Failed to get ChromaDB collection: {e}")
        raise


def get_retriever():
    """获取 HybridRetriever 单例"""
    global _retriever
    if _retriever is None:
        from .retriever import HybridRetriever
        _retriever = HybridRetriever(get_chroma_collection(), get_embedding_function())
    return _retriever


def invalidate_retriever_index():
    """知识库重建后调用, 强制下次查询重建 BM25"""
    if _retriever is not None:
        _retriever.invalidate_index()


# ──────────────────────────────────────────────
# 检索服务
# ──────────────────────────────────────────────

class RetrievalService:
    """统一检索入口: 查询理解 → 混合召回 → 粗排 → 精排 → 父章节扩展 → 预算裁剪"""

    def __init__(self):
        self._reranker = None
        self._rewriter = None

    def _get_reranker(self):
        if self._reranker is not None:
            return self._reranker
        try:
            from .reranker import Reranker
            self._reranker = Reranker()
        except Exception as e:
            logger.warning(f"Reranker unavailable, will skip: {e}")
            self._reranker = False  # 标记不可用
        return self._reranker

    def _get_rewriter(self):
        if self._rewriter is not None:
            return self._rewriter
        try:
            from .query_rewriter import QueryRewriter
            self._rewriter = QueryRewriter()
        except Exception as e:
            logger.warning(f"Query rewriter unavailable: {e}")
            self._rewriter = False
        return self._rewriter

    async def search(self, req: RetrievalRequest) -> RetrievalResult:
        import asyncio, time

        t0 = time.time()
        retriever = get_retriever()

        # ① 查询理解: 多轮改写 (规则短路优先)
        effective_query = req.query
        if req.history:
            rewriter = self._get_rewriter()
            if rewriter:
                effective_query = await asyncio.to_thread(
                    rewriter.condense, req.history, req.query
                )

        # ② 混合检索 (粗排: RRF + 月龄 + 权威度 + 多样性)
        result = await asyncio.to_thread(
            retriever.search, effective_query, k=req.top_k, fetch=req.fetch
        )
        hits_data = result['hits']
        t_retrieve = time.time() - t0

        # ③ 精排 (bge-reranker, 可降级)
        t1 = time.time()
        if req.enable_rerank:
            reranker = self._get_reranker()
            if reranker:
                try:
                    hits_data = await asyncio.to_thread(
                        reranker.rerank, effective_query, hits_data, top_k=req.top_k
                    )
                except Exception as e:
                    logger.warning(f"Rerank failed, using coarse ranking: {e}")
        t_rerank = time.time() - t1

        # ④ 父章节扩展 + 上下文组装 (带预算裁剪)
        expanded_data = retriever.expand_parents(hits_data)
        context = self._build_context(hits_data, expanded_data)

        # ⑤ 组装结果
        hits = [Hit(
            id=h['id'], doc=h.get('doc', ''), meta=h.get('meta') or {},
            score=h.get('score', 0.0), vec_rank=h.get('vec_rank'),
            bm25_rank=h.get('bm25_rank'), age_match=h.get('age_match'), rel='hit',
        ) for h in hits_data]

        expanded = [Hit(
            id=e['id'], doc=e.get('doc', ''), meta=e.get('meta') or {},
            score=e.get('score', 0.0), rel=e.get('rel', 'parent'),
        ) for e in expanded_data]

        sources = [Source(
            index=i + 1,
            title=(h.meta.get('title') or ''),
            filename=(h.meta.get('filename') or ''),
            category=(h.meta.get('category') or ''),
            section=(h.meta.get('section') or ''),
        ) for i, h in enumerate(hits)]

        return RetrievalResult(
            hits=hits, expanded=expanded, context=context, sources=sources,
            debug={
                'effective_query': effective_query,
                'rewritten': effective_query != req.query,
                'vec_n': result['debug']['vec_n'],
                'bm25_n': result['debug']['bm25_n'],
                'fused_n': result['debug']['fused_n'],
                'age_months': result.get('age_months'),
                'retrieve_ms': round(t_retrieve * 1000),
                'rerank_ms': round(t_rerank * 1000),
            },
        )

    def _build_context(self, hits, expanded, max_tokens: int = 2048) -> str:
        """组装上下文: 命中块全量, 父块标注补充, 带总 token 预算裁剪"""
        parts = []
        seen = set()
        budget = max_tokens
        for item in expanded:
            cid = item['id']
            if cid in seen:
                continue
            doc = item.get('doc', '')
            # 近似 token 估算
            tok = self._est_tokens(doc)
            if tok > budget:
                break  # 预算耗尽, 截断低分块
            budget -= tok
            seen.add(cid)
            meta = item.get('meta') or {}
            title = meta.get('title') or meta.get('section') or '未知来源'
            tag = '命中' if item.get('rel') == 'hit' else '补充'
            parts.append(f"【文档{len(parts)+1}·{tag}】标题: {title}\n内容:\n{doc}")
        return '\n\n'.join(parts)

    @staticmethod
    def _est_tokens(text: str) -> int:
        cjk = sum(1 for ch in text
                  if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f')
        other = len(text) - cjk
        return cjk + (other + 3) // 4


# 进程级单例
_service: Optional[RetrievalService] = None


def get_retrieval_service() -> RetrievalService:
    global _service
    if _service is None:
        _service = RetrievalService()
    return _service


# ──────────────────────────────────────────────
# BM25 索引失效联动 (Redis pub/sub)
# ──────────────────────────────────────────────

_invalidate_listener = None


async def _invalidate_listener_task():
    """订阅 kb:invalidate 频道: 知识库重建/增量完成后广播, 本进程同步刷新 BM25"""
    try:
        from ..core.config import get_settings
        import redis.asyncio as aioredis
        r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        await r.ping()
        pubsub = r.pubsub()
        await pubsub.subscribe("kb:invalidate")
        logger.info("BM25 invalidate listener subscribed: kb:invalidate")
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                logger.info("KB invalidate broadcast received, rebuilding BM25 index")
                invalidate_retriever_index()
    except Exception as e:
        logger.warning(f"invalidate listener stopped: {e}")


def start_invalidate_listener():
    """进程启动时调用: 后台监听知识库变更广播 (幂等, 重复调用不重复起线程)"""
    global _invalidate_listener
    if _invalidate_listener is not None and not _invalidate_listener.done():
        return _invalidate_listener
    import asyncio
    try:
        _invalidate_listener = asyncio.get_event_loop().create_task(_invalidate_listener_task())
    except RuntimeError:
        # 无运行中事件循环 (如纯脚本环境) → 跳过
        _invalidate_listener = None
    return _invalidate_listener
