"""
Cross-Encoder 精排 (bge-reranker)
=================================

可降级: 模型不可用或超时时跳过, 回退到粗排结果。
首次加载懒初始化, 进程级单例。
"""

import time
from typing import Any, Dict, List, Optional

from loguru import logger

DEFAULT_MODEL = "BAAI/bge-reranker-base"
RERANK_TIMEOUT_MS = 500  # 精排总超时门限


class Reranker:
    """bge-reranker-base 精排器 (CPU 可跑, 单条 ~50ms)"""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        from sentence_transformers import CrossEncoder
        logger.info(f"Loading reranker model: {model_name}")
        self._model = CrossEncoder(model_name)
        self._model_name = model_name

    def rerank(self, query: str, hits: List[Dict[str, Any]],
               top_k: int = 3) -> List[Dict[str, Any]]:
        """
        对粗排结果精排, 返回 top-k。

        Args:
            query: 检索 query (改写后的 effective_query)
            hits: 粗排结果 [{id, doc, meta, score, ...}]
            top_k: 返回数量
        """
        if not hits:
            return hits

        t0 = time.time()
        pairs = [(query, h.get('doc', '')) for h in hits]
        scores = self._model.predict(pairs)

        for h, s in zip(hits, scores):
            h['rerank_score'] = float(s)

        hits.sort(key=lambda h: -h.get('rerank_score', 0))
        elapsed = (time.time() - t0) * 1000
        logger.debug(f"rerank: {len(hits)} pairs, {elapsed:.0f}ms, top_score={hits[0].get('rerank_score'):.4f}")

        return hits[:top_k]
