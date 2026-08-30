"""
手写 BM25Okapi (零新依赖)
=========================

为什么手写: rank-bm25 不在依赖清单; 核心算法 40 行内可控, 便于面试讲解。
分词: jieba (已在依赖中)。

BM25 公式:
  score(q, d) = Σ_{w∈q} IDF(w) · tf(w,d)·(k1+1) / (tf(w,d) + k1·(1-b+b·|d|/avgdl))
  IDF(w) = ln((N - df(w) + 0.5) / (df(w) + 0.5) + 1)
  k1=1.5 控制词频饱和度, b=0.75 控制文档长度归一化强度
"""

import math
from collections import Counter
from typing import Dict, List, Sequence


class BM25:
    def __init__(self, corpus_tokens: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(corpus_tokens)
        self.doc_tf: List[Counter] = [Counter(t) for t in corpus_tokens]
        self.doc_len: List[int] = [len(t) for t in corpus_tokens]
        self.avgdl = sum(self.doc_len) / max(self.N, 1)

        df: Counter = Counter()
        for toks in corpus_tokens:
            df.update(set(toks))
        self.idf: Dict[str, float] = {
            w: math.log((self.N - d + 0.5) / (d + 0.5) + 1) for w, d in df.items()
        }

    def scores(self, query_tokens: Sequence[str]) -> List[float]:
        """返回每篇文档对该 query 的 BM25 分数 (与语料顺序对齐)"""
        out = []
        for tf, dl in zip(self.doc_tf, self.doc_len):
            s = 0.0
            for w in query_tokens:
                f = tf.get(w)
                if not f:
                    continue
                s += self.idf.get(w, 0.0) * f * (self.k1 + 1) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                )
            out.append(s)
        return out

    def top_n(self, query_tokens: Sequence[str], n: int) -> List[tuple]:
        """返回 [(index, score)] 按分数降序, 只保留 score>0"""
        sc = self.scores(query_tokens)
        pairs = [(i, s) for i, s in enumerate(sc) if s > 0]
        pairs.sort(key=lambda x: -x[1])
        return pairs[:n]
