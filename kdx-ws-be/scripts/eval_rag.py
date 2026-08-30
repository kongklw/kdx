"""
RAG 检索评估集脚本
==================

为什么需要评估集:
  检索策略(纯向量 vs 混合)的切换、参数调优(RRF k/权重)都不能凭感觉,
  必须在固定标注集上量化: 每次改动跑一遍, 指标涨了才算数 —— 这是
  检索优化的回归测试。

标注集格式 (JSON, 支持外部扩充):
  [
    {
      "query": "宝宝辅食什么时候开始加",
      "relevant": ["Weaning.md", "Weaning_and_feeding.md"]   # 相关文档名(命中任一即算)
    }
  ]
  不传 --cases 时使用内置 SEED_CASES (基于真实知识库手工标注)。

指标:
  HitRate@k  : top-k 中至少命中一条相关文档的 query 占比 (召回率, 核心指标)
  MRR        : 第一条相关文档排名倒数的均值 (排序质量)
  AvgRank    : 第一条相关文档的平均排名 (越小越好)

A/B 对比: 同一标注集分别跑 纯向量(旧实现) 与 混合检索(新实现)。

用法:
  uv run python -m scripts.eval_rag                      # 内置 seed 集, k=1,3,5,10
  uv run python -m scripts.eval_rag --cases my.json      # 自定义标注集
  uv run python -m scripts.eval_rag --min-hitrate 0.6    # 低于阈值退出码 1 (可接 CI)
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

# ──────────────────────────────────────────────
# 内置 seed 标注集: 中文口语 query → 知识库真实文档
# (标注规则: 命中所列任一文档的任一 chunk 即算命中)
# ──────────────────────────────────────────────

SEED_CASES: List[Dict[str, Any]] = [
    {"query": "宝宝辅食什么时候开始添加",
     "relevant": ["Weaning.md", "Weaning_and_feeding.md", "婴儿喂养看护知识汇总.md", "婴幼儿喂养健康教育核心信息"]},
    {"query": "母乳喂养有什么好处",
     "relevant": ["Breastfeeding.md", "婴儿喂养看护知识汇总.md", "婴幼儿喂养健康教育核心信息"]},
    {"query": "孩子什么时候可以打流感疫苗",
     "relevant": ["Children's_flu_vaccine.md", "流感.md"]},
    {"query": "水痘疫苗有必要打吗",
     "relevant": ["Chickenpox_vaccine.md", "水痘.md"]},
    {"query": "轮状病毒疫苗是预防什么的",
     "relevant": ["Rotavirus_vaccine.md", "儿童疫苗接种指南.md"]},
    {"query": "宝宝疫苗接种时间表",
     "relevant": ["Vaccine_Schedules.md", "Vaccines_by_Age.md", "儿童疫苗接种指南.md"]},
    {"query": "新生儿怎么护理",
     "relevant": ["Caring_for_a_newborn_baby.md"]},
    {"query": "如厕训练什么时候开始",
     "relevant": ["Potty_Training.md", "儿童如厕训练指南.md"]},
    {"query": "宝宝出牙不舒服怎么办",
     "relevant": ["Teething_&_Tooth_Care.md", "儿童口腔护理指南.md"]},
    {"query": "肺炎球菌疫苗要打几针",
     "relevant": ["Pneumococcal_vaccine.md", "儿童疫苗接种指南.md"]},
    {"query": "HPV疫苗多大可以打",
     "relevant": ["HPV感染.md", "Vaccine_Information_for_Adults.md"]},
    {"query": "孩子发烧还能打疫苗吗",
     "relevant": ["Vaccines_When_Your_Child_Is_Sick.md", "儿童疫苗接种指南.md"]},
]


def load_cases(path: str) -> List[Dict[str, Any]]:
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            cases = json.load(f)
        print(f"[eval] loaded {len(cases)} cases from {path}")
        return cases
    print(f"[eval] using built-in SEED_CASES ({len(SEED_CASES)} cases)")
    return SEED_CASES


# ──────────────────────────────────────────────
# 两条检索通道
# ──────────────────────────────────────────────

def pure_vector_topk(retriever, query: str, k: int) -> List[str]:
    """旧实现: 纯向量 top-k, 返回 chunk id 列表"""
    emb = retriever.embed_fn.embed_query(query)
    res = retriever.collection.query(query_embeddings=emb, n_results=k)
    return list(res['ids'][0])


def hybrid_topk(retriever, query: str, k: int, fetch: int = 20) -> List[str]:
    """新实现: 混合检索 top-k"""
    return [h['id'] for h in retriever.search(query, k=k, fetch=fetch)['hits']]


# ──────────────────────────────────────────────
# 指标计算
# ──────────────────────────────────────────────

def _is_hit(chunk_id: str, relevant: List[str]) -> bool:
    """子串双向匹配 (大小写不敏感): '水痘.md' 命中 '水痘.md_3',
    '婴幼儿喂养健康教育核心信息' 命中超长文件名"""
    base = chunk_id.rsplit('_', 1)[0].lower()
    return any(r.lower() in base or base in r.lower() for r in relevant)


def _first_hit_rank(ids: List[str], relevant: List[str]) -> int:
    for i, cid in enumerate(ids, 1):
        if _is_hit(cid, relevant):
            return i
    return 0


def evaluate_channel(name: str, topk_fn, cases: List[Dict], k_list: List[int]) -> Dict[str, Any]:
    """在标注集上评估一条检索通道, 返回汇总指标 + 逐 case 明细"""
    kmax = max(k_list)
    detail = []
    for c in cases:
        t0 = time.time()
        ids = topk_fn(c['query'], kmax)
        dt = (time.time() - t0) * 1000
        rank = _first_hit_rank(ids, c['relevant'])
        detail.append({
            'query': c['query'],
            'relevant': c['relevant'],
            'rank': rank,                      # 0 = 未命中
            'latency_ms': round(dt),
            'top_ids': ids[:max(k_list)],
        })

    summary: Dict[str, Any] = {'channel': name, 'n_cases': len(cases)}
    for k in k_list:
        hits = sum(1 for d in detail if 0 < d['rank'] <= k)
        summary[f'HitRate@{k}'] = round(hits / len(cases), 3)
    rr = [1 / d['rank'] for d in detail if d['rank'] > 0]
    summary['MRR'] = round(sum(rr) / len(cases), 3)
    ranks = [d['rank'] for d in detail if d['rank'] > 0]
    summary['AvgRank'] = round(sum(ranks) / len(ranks), 2) if ranks else None
    summary['AvgLatencyMs'] = round(sum(d['latency_ms'] for d in detail) / len(detail))
    return {'summary': summary, 'detail': detail}


def print_report(results: List[Dict[str, Any]], show_detail: bool) -> None:
    print("\n" + "═" * 66)
    print("RAG 检索评估报告")
    print("═" * 66)
    for r in results:
        s = r['summary']
        print(f"\n── {s['channel']} ({s['n_cases']} cases) ──")
        for key, val in s.items():
            if key not in ('channel', 'n_cases'):
                print(f"  {key:14s} {val}")

    # A/B 对比表
    if len(results) == 2:
        print("\n── A/B 对比 (混合 - 纯向量) ──")
        a, b = results[0]['summary'], results[1]['summary']
        for key in a:
            if key in ('channel', 'n_cases'):
                continue
            va, vb = a[key], b[key]
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                diff = vb - va
                print(f"  {key:14s} {va:>8} → {vb:>8}  ({'+' if diff >= 0 else ''}{diff:.3f})")

    if show_detail:
        for r in results:
            print(f"\n── {r['summary']['channel']} 逐 case 明细 ──")
            for d in r['detail']:
                mark = f"rank={d['rank']}" if d['rank'] else "MISS"
                print(f"  [{mark:>8}] {d['query']}  ({d['latency_ms']}ms)")
                if not d['rank']:
                    print(f"            relevant={d['relevant']}")
                    print(f"            got     ={[i.rsplit('_', 1)[0] for i in d['top_ids'][:5]]}")


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="RAG 检索评估")
    ap.add_argument('--cases', default='', help='标注集 JSON 路径 (缺省用内置 seed 集)')
    ap.add_argument('--k', nargs='+', type=int, default=[1, 3, 5, 10], help='HitRate 的 k 值')
    ap.add_argument('--min-hitrate', type=float, default=0.0,
                    help='混合检索 HitRate@max(k) 低于该值时退出码 1 (CI 门禁)')
    ap.add_argument('--no-detail', action='store_true', help='不打印逐 case 明细')
    args = ap.parse_args()

    sys.path.insert(0, os.getcwd())
    from dotenv import load_dotenv
    load_dotenv('.env')
    from app.ws.rag_query import get_retriever

    retriever = get_retriever()
    cases = load_cases(args.cases)

    results = [
        evaluate_channel('纯向量(旧实现)', lambda q, k: pure_vector_topk(retriever, q, k), cases, args.k),
        evaluate_channel('混合检索(新实现)', lambda q, k: hybrid_topk(retriever, q, k), cases, args.k),
    ]
    print_report(results, show_detail=not args.no_detail)

    # CI 门禁
    kmax = max(args.k)
    gate = results[1]['summary'][f'HitRate@{kmax}']
    if args.min_hitrate and gate < args.min_hitrate:
        print(f"\n[FAIL] HitRate@{kmax}={gate} < 门禁 {args.min_hitrate}")
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
