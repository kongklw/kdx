"""
RAG 文档切分 (Chunking) 生产级最佳实践
======================================

为什么切分决定 RAG 上限:
  召回质量 = f(切分质量)。切得太碎 → 单块语义不完整, 向量表征失真;
  切得太粗 → 一块塞多个主题, 与 query 的相似度被稀释。
  Embedding 模型对"语义连贯、长度均匀"的文本块表征最好 —— 切分器的
  职责就是把文档重组成这种形态。

本文件对应 scripts/load_rag_knowledge.py 的生产实现, 修复了它的三个不足:
  1. chunk_overlap 参数未生效        → 块间原子单元重叠
  2. 只认 ## 一级标题 / 表格被切碎   → 多级标题栈 + 表格原子保护
  3. 按字符数不按 token 数           → CJK 感知的近似 token 计量

生产决策维度 (面试核心):
  ┌────────────┬──────────────────────────────────────────────┐
  │ 维度        │ 决策                                          │
  ├────────────┼──────────────────────────────────────────────┤
  │ 粒度        │ 128~512 token; QA对=一问一答一块; 代码=一个函数 │
  │ 边界        │ 结构边界(标题/段落/表格) > 语义边界(句子) > 固定窗口 │
  │ 重叠        │ 10%~15% 粒度; 跨边界语义靠 overlap 兜底          │
  │ 元数据       │ 标题路径/主题/适用人群/权威度 → 过滤与加权排序       │
  │ 检索↔返回解耦 │ small-to-big: 检索用小块(准), 返回父章节(全)     │
  │ 评估        │ 块级: 边界完整率/长度分布; 端到端: recall@k A/B    │
  └────────────┴──────────────────────────────────────────────┘

各文档类型策略:
  - Markdown/HTML   : 按标题层级切, 标题路径入元数据
  - PDF/扫描件      : 先版面解析(unstructured/pymupdf)还原结构, 再按段落+版面块
  - FAQ/QA 对       : 一问一答一块, question 前置并重复进向量(问法匹配)
  - 代码            : 按函数/类边界(AST), docstring 必须与函数同块
  - 表格            : 整表原子, 不跨块; 检索命中时转 Markdown 文本给 LLM
  - 对话日志        : 按轮次窗口切, 保留说话人标签

运行: cd kdx-ws-be && uv run python -m app.example.chunking_best_practices
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════
# 通用生产级切分器 (与 scripts/load_rag_knowledge.py 同构, 参数化泛化)
# ═══════════════════════════════════════════════════════════

def est_tokens(text: str) -> int:
    """近似 token: CJK 1字≈1token, 其他 4字符≈1token (text2vec/bge 对中文基本 1字1token)"""
    cjk = sum(1 for ch in text
              if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f'
              or '\uff00' <= ch <= '\uffef')
    return cjk + (len(text) - cjk + 3) // 4


@dataclass
class Chunk:
    content: str
    section: str                       # 完整标题路径 "H1 > H2 > H3"
    parent_section: str = ""           # 父标题路径 (small-to-big 用)
    meta: dict = field(default_factory=dict)


def parse_units(md: str):
    """markdown → 原子单元 [(title_path, kind, text)], kind ∈ heading/para/table"""
    units, stack, buf, is_table = [], [], [], False

    def flush():
        nonlocal buf, is_table
        if buf:
            path = ' > '.join(t for _, t in stack) or '正文'
            units.append((path, 'table' if is_table else 'para', '\n'.join(buf).strip()))
        buf, is_table = [], False

    for line in md.split('\n'):
        s = line.strip()
        m = re.match(r'^(#{1,6})\s+(.+)$', s)
        if m:
            flush()
            lv, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= lv:
                stack.pop()
            stack.append((lv, title))
            units.append((' > '.join(t for _, t in stack), 'heading', s))
        elif s.startswith('|'):
            if buf and not is_table:
                flush()
            is_table = True
            buf.append(line.rstrip())
        elif not s:
            flush()
        else:
            if is_table:
                flush()
            buf.append(line.rstrip())
    flush()
    return units


def hard_split(text: str, max_tokens: int, overlap: int):
    """超长段落兜底: 句子级切, 同样带 overlap"""
    sents = [s for s in re.split(r'(?<=[。！？!?\n])', text) if s.strip()]
    out, buf, blen = [], [], 0
    for s in sents:
        sl = est_tokens(s)
        if buf and blen + sl > max_tokens:
            out.append(''.join(buf).strip())
            tail, tl = [], 0
            for x in reversed(buf):
                xl = est_tokens(x)
                if tl + xl > overlap and tail:
                    break
                tail.insert(0, x)
                tl += xl
            buf, blen = tail, tl
        buf.append(s)
        blen += sl
    if ''.join(buf).strip():
        out.append(''.join(buf).strip())
    return [s for s in out if s]


def structural_chunk(md: str, chunk_size: int = 500, chunk_overlap: int = 50,
                     min_chunk: int = 80):
    """
    三阶段结构感知切分 (生产版):
      1) heading 开章节组
      2) 短节(<min_chunk)向前合并, 防碎块
      3) 组内打包: 封口时尾部回取完整单元作 overlap (不跨 heading/表格)
    """
    units = parse_units(md)
    if not units:
        return []

    # 阶段1
    sections = []
    for path, kind, text in units:
        if kind == 'heading' or not sections:
            sections.append([path, []])
        sections[-1][1].append((kind, text))

    # 阶段2: 短节合并
    groups = []
    for path, us in sections:
        if groups:
            prev_size = est_tokens('\n\n'.join(t for _, t in groups[-1][1]))
            if prev_size < min_chunk:
                groups[-1][1].extend(us)
                continue
        groups.append([path, list(us)])
    if len(groups) > 1 and \
            est_tokens('\n\n'.join(t for _, t in groups[-1][1])) < min_chunk:
        groups[-2][1].extend(groups.pop()[1])

    # 阶段3: 打包 + overlap
    chunks = []
    for path, us in groups:
        buf, blen = [], 0
        for kind, text in us:
            tl = est_tokens(text) + 1
            if tl > chunk_size:                       # 超长单元: 句子级兜底
                if buf:
                    chunks.append(_mk(buf, path))
                    buf, blen = [], 0
                chunks.extend(_mk([('para', s)], path) for s in
                              hard_split(text, chunk_size, chunk_overlap))
                continue
            if buf and blen + tl > chunk_size:
                chunks.append(_mk(buf, path))
                # overlap: 尾部回取完整单元 (不跨 heading, 不超预算/半块)
                tail, tlen = [], 0
                for k, t in reversed(buf):
                    l = est_tokens(t) + 1
                    if k == 'heading' or (tail and tlen + l > chunk_overlap) \
                            or tlen + l > chunk_size // 2:
                        break
                    tail.insert(0, (k, t))
                    tlen += l
                buf, blen = tail, tlen
            buf.append((kind, text))
            blen += tl
        if buf:
            chunks.append(_mk(buf, path))
    return chunks


def _mk(buf, section: str) -> Chunk:
    parts = section.split(' > ')
    return Chunk(
        content='\n\n'.join(t for _, t in buf),
        section=section,
        parent_section=' > '.join(parts[:-1]) if len(parts) > 1 else section,
    )


def naive_chunk(md: str, size: int = 500):
    """对照组: 固定字符窗口 (无结构感知) —— 生产反例"""
    return [md[i:i + size] for i in range(0, len(md), size)]


# ═══════════════════════════════════════════════════════════
# 块质量评估指标 (生产闭环: 先块级体检, 再端到端 A/B)
# ═══════════════════════════════════════════════════════════

def chunk_quality_report(chunks, budget: int = 500):
    """块级体检: 长度分布 / 边界完整率 / 标题覆盖率"""
    lens = [est_tokens(c.content if isinstance(c, Chunk) else c) for c in chunks]
    bodies = [c.content if isinstance(c, Chunk) else c for c in chunks]
    boundary_ok = sum(1 for b in bodies
                      if b.rstrip().endswith(('。', '！', '？', '：', '|', '\n')))
    title_kept = sum(1 for c in chunks
                     if isinstance(c, Chunk) and c.section != '正文')
    return {
        'n_chunks': len(chunks),
        'len_min/avg/max': (min(lens), sum(lens) // len(lens), max(lens)),
        'budget_violations': sum(1 for l in lens if l > budget * 1.25),
        'boundary_integrity': f'{boundary_ok}/{len(bodies)}',
        'with_title_meta': f'{title_kept}/{len(chunks)}',
    }


# ═══════════════════════════════════════════════════════════
# 运行示例: 结构感知 vs 固定窗口 对比
# ═══════════════════════════════════════════════════════════

SAMPLE = """# 婴儿睡眠指南

## 睡眠安全

一岁以内婴儿应仰卧入睡，床上不放置柔软枕头与毛绒玩具，降低窒息风险。

| 阶段 | 推荐睡姿 | 风险提示 |
|------|----------|----------|
| 0-6个月 | 仰卧 | 避免俯卧 |
| 6-12个月 | 仰卧为主 | 可自主翻身 |

## 作息培养

建立固定睡前程序：洗澡、抚触、喂奶、关灯，每天同一时间进行。
昼夜区分要明显，白天小睡不拉窗帘，夜间睡眠保持黑暗安静。
""" + "夜醒频繁时先排查饥饿、肠胀气、出牙不适等生理原因，再考虑睡眠联想问题。" * 8 + """

## 常见误区

摇晃入睡会形成依赖，应逐渐降低安抚强度，让婴儿学习自主入睡。
"""


def demo():
    print("═" * 62)
    print("结构感知切分 vs 固定窗口切分 (同一文档)")
    print("═" * 62)

    smart = structural_chunk(SAMPLE)
    naive = naive_chunk(SAMPLE)

    print("\n── 结构感知 (生产版) ──")
    for i, c in enumerate(smart):
        print(f"[{i}] sec={c.section!r}")
        print(f"    parent={c.parent_section!r} tok={est_tokens(c.content)}")
        print(f"    {c.content[:40].replace(chr(10), '⏎')}...")

    print("\n── 固定窗口 (反例) ──")
    for i, c in enumerate(naive[:3]):
        print(f"[{i}] {c[:40].replace(chr(10), '⏎')}...")

    print("\n── 块质量体检 ──")
    print("smart:", chunk_quality_report(smart))
    print("naive:", chunk_quality_report(naive))

    # 断言
    table_smart = next((c for c in smart if '| 米粉' in c.content or '| 0-6个月' in c.content), None)
    table_ok = table_smart and table_smart.content.count('|') >= 8  # 表格未被拆散
    naive_table = next((c for c in naive if '| 0-6个月' in c), None)
    naive_ok = naive_table and naive_table.count('|') >= 8
    print(f"\nTABLE_INTACT  smart={bool(table_ok)} naive={bool(naive_ok)}")
    print("SECTION_META  smart 有标题路径元数据, naive 无法提供 → 无法做元数据过滤")
    print("\nCHUNKING_DEMO_OK")


if __name__ == '__main__':
    demo()
