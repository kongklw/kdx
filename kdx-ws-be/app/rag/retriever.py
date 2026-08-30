"""
混合检索器 (生产级 RAG 检索层)
==============================

流水线: 混合召回 → 月龄软过滤 → 加权精排 → 父章节扩展 (small-to-big)

  1) 混合召回: 向量(语义) top-F + BM25(关键词) top-F, RRF 融合
     —— 向量漏关键词硬匹配 (如疫苗名"脊灰"), BM25 漏同义改写, 互补
  2) 月龄软过滤: 从 query 抽月龄, 与 meta.age_ranges 匹配的文档加权;
     不硬过滤 (元数据缺失/解析失败时优雅降级, 只影响排序不丢结果)
  3) 精排: final = rrf_norm + age_boost + w_authority·authority_norm
     生产可替换 Cross-Encoder 重排 (bge-reranker), search() 接口不变
  4) 父章节扩展: 命中块按 parent_section 回溯相邻块拼入上下文
     —— 检索用小块保证精准, 返回用父章节保证完整 (依赖重切分入库后生效)

对旧索引容错: 元数据缺 section/age_ranges 时自动跳过对应阶段。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

import jieba

from .bm25 import BM25


# ──────────────────────────────────────────────
# 月龄抽取与匹配
# ──────────────────────────────────────────────

_AGE_PATTERNS = [
    (re.compile(r'(\d+(?:\.\d+)?)\s*个?月'), lambda v: float(v)),
    (re.compile(r'(\d+(?:\.\d+)?)\s*周?岁'), lambda v: float(v) * 12),
]


def extract_age_months(query: str) -> Optional[float]:
    """从 query 抽取月龄: '6个月'→6.0, '1岁'→12.0; 无则 None"""
    for pat, conv in _AGE_PATTERNS:
        m = pat.search(query)
        if m:
            return conv(m.group(1))
    return None


def _parse_age_range(meta: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """
    解析 age_ranges 元数据, 多格式容错:
      [6, 8] / "6-8个月" / "0-1岁" / "6个月" → (lo, hi) 单位: 月
      缺失/无法解析 → None (调用方跳过过滤)
    """
    raw = (meta or {}).get('age_ranges')
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and raw:
        try:
            nums = sorted(float(x) for x in raw)
            return (nums[0], nums[-1])
        except (TypeError, ValueError):
            return None
    if isinstance(raw, str):
        nums = re.findall(r'(\d+(?:\.\d+)?)', raw)
        if not nums:
            return None
        vals = [float(x) for x in nums]
        if '岁' in raw and '月' not in raw:
            vals = [v * 12 for v in vals]
        return (vals[0], vals[-1]) if len(vals) > 1 else (vals[0], vals[0])
    return None


def age_match(meta: Dict[str, Any], months: Optional[float]) -> Optional[bool]:
    """月龄匹配: True/False; 元数据缺失 → None (既不加分也不降权)"""
    if months is None:
        return None
    rng = _parse_age_range(meta)
    if rng is None:
        return None
    lo, hi = rng
    return lo - 3 <= months <= hi + 3     # ±3 个月容差


# ──────────────────────────────────────────────
# 混合检索器
# ──────────────────────────────────────────────

class HybridRetriever:
    def __init__(self, collection, embed_fn,
                 rrf_k: int = 60, w_vec: float = 0.0, w_bm25: float = 0.0,
                 age_boost: float = 0.15, w_authority: float = 0.1):
        """
        w_vec/w_bm25 已融合进 RRF (双路命中自然得分高), 保留参数为将来
        分数级融合 (cosine·w + bm25_norm·w) 预留; 当前用 RRF 排名融合。
        """
        self.collection = collection
        self.embed_fn = embed_fn
        self.rrf_k = rrf_k
        self.w_vec, self.w_bm25 = w_vec, w_bm25
        self.age_boost = age_boost
        self.w_authority = w_authority
        self._index: Optional[Dict[str, Any]] = None   # 懒构建 BM25 索引

    # ── 索引: 首次查询拉全量语料构建 BM25 ──
    def _ensure_index(self) -> None:
        if self._index is not None:
            return
        data = self.collection.get(include=['documents', 'metadatas'])
        docs = [d or '' for d in data['documents']]
        tokenized = [list(jieba.cut_for_search(d)) for d in docs]
        self._index = {
            'ids': list(data['ids']),
            'docs': docs,
            'metas': data['metadatas'],
            'bm25': BM25(tokenized),
            'id_pos': {cid: i for i, cid in enumerate(data['ids'])},
        }

    def invalidate_index(self) -> None:
        """知识库重建后调用, 强制下次查询重建 BM25"""
        self._index = None

    # ── 主流程 ──
    def search(self, query: str, k: int = 3, fetch: int = 20) -> Dict[str, Any]:
        """
        返回 {
          'hits':     [{id, doc, meta, score, age_match, vec_rank, bm25_rank}...],  # top-k
          'expanded': [{...同上, rel: 'hit'|'parent'}],   # 父章节扩展后的上下文块
          'age_months': float|None,
          'debug':    {'vec_n': int, 'bm25_n': int, 'fused_n': int},
        }
        """
        self._ensure_index()
        idx = self._index
        months = extract_age_months(query)
        n_docs = max(self.collection.count(), 1)

        # 1) 双路召回
        q_emb = self.embed_fn.embed_query(query)
        vec = self.collection.query(query_embeddings=q_emb, n_results=min(fetch, n_docs))
        vec_ids = list(vec['ids'][0])
        vec_dist = list(vec.get('distances', [[]])[0])
        bm_pairs = idx['bm25'].top_n(list(jieba.cut_for_search(query)), fetch)

        # 2) RRF 融合: score = Σ 1/(k + rank)
        fused: Dict[str, Dict[str, Any]] = {}
        for rank, cid in enumerate(vec_ids):
            d = fused.setdefault(cid, {'id': cid, 'vec_rank': None, 'bm25_rank': None,
                                       'vec_dist': None, 'rrf': 0.0})
            d['vec_rank'] = rank
            d['vec_dist'] = vec_dist[rank] if rank < len(vec_dist) else None
            d['rrf'] += 1.0 / (self.rrf_k + rank + 1)
        for rank, (i, _s) in enumerate(bm_pairs):
            cid = idx['ids'][i]
            d = fused.setdefault(cid, {'id': cid, 'vec_rank': None, 'bm25_rank': None,
                                       'vec_dist': None, 'rrf': 0.0})
            d['bm25_rank'] = rank
            d['rrf'] += 1.0 / (self.rrf_k + rank + 1)

        # 3) 月龄软过滤 + 权威度加权
        max_rrf = max((d['rrf'] for d in fused.values()), default=0.0)
        for d in fused.values():
            pos = idx['id_pos'].get(d['id'])
            meta = idx['metas'][pos] if pos is not None else {}
            d['meta'] = meta
            d['doc'] = idx['docs'][pos] if pos is not None else ''

            am = age_match(meta, months)
            d['age_match'] = am
            boost = self.age_boost if am else (0.0 if am is None else -self.age_boost / 2)
            auth = (meta or {}).get('authority')
            auth_n = (float(auth) / 5.0) if isinstance(auth, (int, float)) else 0.5
            d['score'] = (d['rrf'] / max_rrf if max_rrf > 0 else 0.0) \
                + boost + self.w_authority * (auth_n - 0.5)

        hits_all = sorted(fused.values(), key=lambda d: -d['score'])

        # 4) 文档级多样性 top-k: 同文档只取最高分块, 避免同文档多 chunk 挤占名额
        #    被挤掉的同文档邻居块 → 父章节扩展来补上下文
        diverse = []
        seen_docs = set()
        for d in hits_all:
            doc_base = d['id'].rsplit('_', 1)[0]
            if doc_base not in seen_docs:
                diverse.append(d)
                seen_docs.add(doc_base)
            if len(diverse) >= k:
                break
        top = diverse

        # 5) 父章节扩展
        expanded = self.expand_parents(top)

        return {
            'hits': top,
            'expanded': expanded,
            'age_months': months,
            'debug': {'vec_n': len(vec_ids), 'bm25_n': len(bm_pairs), 'fused_n': len(fused)},
        }

    # ── 父章节扩展 (small-to-big): 旧索引无 parent_section 时优雅降级 ──
    def expand_parents(self, top: List[Dict[str, Any]],
                        max_extra_per_hit: int = 1,
                        max_expand_tokens: int = 600) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        budget = max_expand_tokens
        for d in top:
            out.append({**d, 'rel': 'hit'})
            meta = d.get('meta') or {}
            parent, cidx = meta.get('parent_section'), meta.get('chunk_index')
            if cidx is None:
                continue
            taken = 0
            for delta in (1, -1):
                if taken >= max_extra_per_hit or budget <= 0:
                    break
                pos = self._find_sibling(d['id'], int(cidx) + delta)
                if pos is None:
                    continue
                sib_meta = self._index['metas'][pos] or {}
                # 有 parent_section 时要求同父章节; 旧索引无该字段时相邻块即扩展
                if parent and sib_meta.get('parent_section') != parent:
                    continue
                doc = self._index['docs'][pos]
                if len(doc) > budget:
                    continue
                budget -= len(doc)
                taken += 1
                out.append({'id': self._index['ids'][pos], 'doc': doc,
                            'meta': sib_meta, 'score': 0.0, 'rel': 'parent'})
        return out

    def _find_sibling(self, hit_id: str, sibling_idx: int) -> Optional[int]:
        base = hit_id.rsplit('_', 1)[0]
        return self._index['id_pos'].get(f"{base}_{sibling_idx}")
