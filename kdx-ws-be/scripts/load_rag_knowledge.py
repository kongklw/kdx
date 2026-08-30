#!/usr/bin/env python3
"""
RAG 知识库加载脚本
使用 text2vec-base-chinese 作为 Embedding 模型，ChromaDB 作为向量数据库
优化：基于章节的分块、元数据丰富、去重、质量过滤
"""

import os
import json
import shutil
import re
from pathlib import Path

RAG_DATA_DIR = Path(__file__).parent.parent / 'data' / 'rag' / 'baby_feeding'
CHROMA_DB_DIR = Path(__file__).parent.parent / 'data' / 'chroma_db'

TOPIC_KEYWORDS = {
    '喂养营养': ['喂养', '辅食', '营养', '母乳', '配方奶', '膳食', '饮食', '断奶', '吃奶', '奶量'],
    '生长发育': ['发育', '里程碑', '身高', '体重', '头围', '运动', '语言', '认知', '能力'],
    '疫苗接种': ['疫苗', '接种', '免疫', '预防', '乙肝', '卡介苗', '脊灰', '百白破'],
    '睡眠作息': ['睡眠', '作息', '入睡', '夜醒', '午睡', '生物钟', '睡觉', '睡整觉'],
    '口腔护理': ['口腔', '牙齿', '刷牙', '龋齿', '长牙', '口腔卫生', '牙胶'],
    '皮肤护理': ['皮肤', '湿疹', '尿布疹', '痱子', '护肤', '保湿', '过敏', '红疹'],
    '急救安全': ['急救', '安全', '窒息', '烫伤', '溺水', '外伤', '防护', '意外'],
    '常见疾病': ['疾病', '感冒', '发烧', '腹泻', '便秘', '肺炎', '哮喘', '咳嗽'],
    '心理健康': ['心理', '情绪', '焦虑', '社交', '性格', '行为', '心理发展'],
    '早期教育': ['早教', '教育', '学习', '游戏', '认知', '阅读', '玩具', '亲子'],
    '视力听力': ['视力', '听力', '眼睛', '耳朵', '弱视', '近视', '听力筛查'],
    '如厕训练': ['如厕', '大小便', '训练', '尿布', '马桶', '尿床'],
}

AGE_RANGE_KEYWORDS = {
    '0-6个月': ['新生儿', '0-3个月', '3-6个月', '出生', '婴儿早期'],
    '6-12个月': ['6个月', '7个月', '8个月', '9个月', '10个月', '11个月', '周岁'],
    '1-3岁': ['1岁', '1-2岁', '2岁', '2-3岁', '3岁', '幼儿'],
    '3-6岁': ['3-4岁', '4岁', '5岁', '6岁', '学龄前'],
}

SOURCE_AUTHORITY = {
    '国家卫生健康委': 5,
    '中国疾控中心': 5,
    'WHO': 5,
    'UNICEF中国': 5,
    '美国CDC': 5,
    '美国儿科学会': 5,
    '英国NHS': 5,
    'Mayo Clinic': 5,
    '中国妇幼保健协会': 4,
    '中国营养学会': 4,
    '健康中国': 4,
    '妇幼健康': 4,
    '综合知识': 3,
    '搜索结果': 2,
}


def detect_topics(content):
    topics = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in content for kw in keywords):
            topics.append(topic)
    return topics if topics else ['综合知识']


def detect_age_range(content):
    age_ranges = []
    for age_range, keywords in AGE_RANGE_KEYWORDS.items():
        if any(kw in content for kw in keywords):
            age_ranges.append(age_range)
    return age_ranges if age_ranges else ['0-3岁']


def get_authority_level(category):
    return SOURCE_AUTHORITY.get(category, 3)


# ──────────────────────────────────────────────
# 切分辅助: 近似 token 长度 (优化3: token 感知替代纯字符数)
# ──────────────────────────────────────────────

def _est_tokens(text: str) -> int:
    """
    近似 token 估算: CJK(含中文标点/全角) 1字≈1token, 其他 4字符≈1token。
    不用 tiktoken 的原因: 需联网下载 BPE 词表, 且对中文 embedding 场景只是近似。
    text2vec 的分词器对中文基本 1 字 1 token, 该估算误差 <15%, 足够控制块长。
    """
    cjk = 0
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef':
            cjk += 1
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def _parse_units(content: str):
    """
    把 markdown 线性解析为原子单元序列 (保序):
      unit = (title_path, kind, text),  kind ∈ {heading, para, table}

    优化2: 多级标题(#..######)入标题栈 → 每块携带完整标题路径;
           连续 '|' 行聚合为表格原子块, 表格永不跨块拆散。
    """
    units = []
    stack = []          # [(level, title)] 当前标题栈
    buf, buf_is_table = [], False

    def _path():
        return ' > '.join(t for _, t in stack) if stack else '正文'

    def flush_para():
        nonlocal buf, buf_is_table
        if buf:
            text = '\n'.join(buf).strip()
            if text:
                units.append((_path(), 'table' if buf_is_table else 'para', text))
            buf, buf_is_table = [], False

    for line in content.split('\n'):
        stripped = line.strip()
        m = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if m:
            flush_para()
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            units.append((_path(), 'heading', stripped))
        elif stripped.startswith('|'):
            if buf and not buf_is_table:
                flush_para()
            buf_is_table = True
            buf.append(line.rstrip())
        elif not stripped:
            flush_para()
        else:
            if buf_is_table:
                flush_para()
            buf.append(line.rstrip())
    flush_para()
    return units


def _make_chunk(buf, section: str) -> dict:
    path = section.split(' > ')
    return {
        'content': '\n\n'.join(t for _, t in buf),
        'section': section,
        # 父标题路径 (small-to-big: 检索用小块, 返回时可扩到父章节)
        'parent_section': ' > '.join(path[:-1]) if len(path) > 1 else section,
    }


def _hard_split(text: str, chunk_size: int, chunk_overlap: int):
    """超长段落兜底: 句子级硬切, 同样带 overlap (避免单段 >chunk_size 时溢出)"""
    sents = [s for s in re.split(r'(?<=[。！？!?\n])', text) if s.strip()]
    out, buf, blen = [], [], 0
    for s in sents:
        sl = _est_tokens(s)
        if buf and blen + sl > chunk_size:
            out.append(''.join(buf).strip())
            tail, tl = [], 0
            for x in reversed(buf):
                xl = _est_tokens(x)
                if tl + xl > chunk_overlap and tail:
                    break
                tail.insert(0, x)
                tl += xl
            buf, blen = tail, tl
        buf.append(s)
        blen += sl
    if ''.join(buf).strip():
        out.append(''.join(buf).strip())
    return [s for s in out if s]


def _tail_overlap(buf, chunk_overlap: int, chunk_size: int):
    """块尾重叠: 从尾部回取完整原子单元, 不跨 heading、不超 overlap 预算、不超半块"""
    tail, tlen = [], 0
    for kind, text in reversed(buf):
        tl = _est_tokens(text) + 1
        if kind == 'heading' or (tail and tlen + tl > chunk_overlap) \
                or tlen + tl > chunk_size // 2:
            break
        tail.insert(0, (kind, text))
        tlen += tl
    return tail, tlen


def split_document_by_section(content, chunk_size=500, chunk_overlap=50):
    """
    结构感知切分 (生产版, 三阶段流水线: 分组→短节合并→打包+overlap)

    优化1 (overlap): 阶段3 封口时尾部回取完整单元作下一块开头, 不截半句/半表,
                     不跨 heading 语义边界, 总量 ≤ chunk_overlap 且 ≤ 半块。
    优化2 (结构感知): 多级标题(#..######)开启章节组, section 为完整标题路径;
                      段落/表格是原子单元 —— 表格永不跨块, 句子永不被切断。
    优化3 (token):   长度按近似 token 计量 (_est_tokens), 中文按字英文按词。
    短节合并 (MIN_CHUNK_TOKENS) 避免碎块被质量过滤丢弃。
    """
    units = _parse_units(content)
    if not units:
        return []

    # 阶段1: heading 开启章节组, 组内累计原子单元
    sections = []                                   # [[path, [(kind, text)]]]
    for path, kind, text in units:
        if kind == 'heading' or not sections:
            sections.append([path, []])
        sections[-1][1].append((kind, text))

    # 阶段2: 短章节合并 (向前并入), 防止产生 <MIN_CHUNK 的碎块
    MIN_CHUNK_TOKENS = 80
    groups = []
    for path, us in sections:
        size = _est_tokens('\n\n'.join(t for _, t in groups[-1][1])) if groups else 0
        if groups and size < MIN_CHUNK_TOKENS:
            groups[-1][1].extend(us)                # 并入前组, 保留前组路径
        else:
            groups.append([path, list(us)])
    if len(groups) > 1 and \
            _est_tokens('\n\n'.join(t for _, t in groups[-1][1])) < MIN_CHUNK_TOKENS:
        groups[-2][1].extend(groups.pop()[1])       # 末组过短并入前一组

    # 阶段3: 组内线性打包, 超长封口并回取 overlap
    chunks = []
    for path, us in groups:
        buf, blen = [], 0
        for kind, text in us:
            tl = _est_tokens(text) + 1
            if tl > chunk_size:                     # 单元超长: 句子级硬切兜底
                if buf:
                    chunks.append(_make_chunk(buf, path))
                    buf, blen = [], 0
                for seg in _hard_split(text, chunk_size, chunk_overlap):
                    chunks.append(_make_chunk([('para', seg)], path))
                continue
            if buf and blen + tl > chunk_size:
                chunks.append(_make_chunk(buf, path))
                buf, blen = _tail_overlap(buf, chunk_overlap, chunk_size)
            buf.append((kind, text))
            blen += tl
        if buf:
            chunks.append(_make_chunk(buf, path))
    return chunks


def deduplicate_chunks(chunks):
    seen = set()
    unique_chunks = []
    for chunk in chunks:
        chunk_hash = hash(chunk['content'])
        if chunk_hash not in seen:
            seen.add(chunk_hash)
            unique_chunks.append(chunk)
    return unique_chunks


def filter_low_quality_chunks(chunks, min_length=100):
    return [chunk for chunk in chunks if len(chunk['content']) >= min_length]


def extract_metadata_from_content(content):
    title_match = re.search(r'^#\s+(.+)', content)
    title = title_match.group(1).strip() if title_match else '未命名文档'

    source_match = re.search(r'\*\*来源\*\*:\s*\[(.+)\]\(.+\)', content)
    source = source_match.group(1).strip() if source_match else '未知来源'


    return {
        'title': title,
        'source': source,
        'topics': detect_topics(content),
        'age_ranges': detect_age_range(content),
    }


def load_markdown_files():
    documents = []
    seen_titles = set()

    for category in os.listdir(RAG_DATA_DIR):

        category_path = RAG_DATA_DIR / category


        if os.path.isdir(category_path) and category != '__pycache__':
            for filename in os.listdir(category_path):
                if filename.endswith('.md') and filename != 'Untitled.md':
                    filepath = category_path / filename

                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        metadata = extract_metadata_from_content(content)
                        if metadata['title'] in seen_titles:
                            print(f"重复文档跳过: {metadata['title']}")
                            continue
                        seen_titles.add(metadata['title'])

                        documents.append({
                            'category': category,
                            'filename': filename,
                            'content': content,
                            'filepath': str(filepath),
                            'title': metadata['title'],
                            'topics': metadata['topics'],
                            'age_ranges': metadata['age_ranges'],
                            'authority': get_authority_level(category),
                        })

                    except Exception as e:
                        print(f"读取文件失败 {filepath}: {e}")

    print(f"加载了 {len(documents)} 个去重后的文档")
    return documents


def split_document(content, chunk_size=500, chunk_overlap=50):
    chunks = split_document_by_section(content, chunk_size, chunk_overlap)
    chunks = filter_low_quality_chunks(chunks)
    chunks = deduplicate_chunks(chunks)
    return chunks


def init_chroma_db(documents):
    import time
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from chromadb import PersistentClient
    from app.scripts.text2vec_embedding_text2vec import Text2VecEmbeddingFunction

    print("Step 1: Creating embedding function...")
    t0 = time.time()
    embedding_function = Text2VecEmbeddingFunction()
    t1 = time.time()
    print(f"Step 1 done: Embedding function loaded in {t1 - t0:.2f}s: {embedding_function.name()}")

    if CHROMA_DB_DIR.exists():
        shutil.rmtree(CHROMA_DB_DIR)
        print("Existing ChromaDB cleared")

    print("Step 2: Creating PersistentClient...")
    t0 = time.time()
    client = PersistentClient(path=str(CHROMA_DB_DIR))
    t1 = time.time()
    print(f"Step 2 done: PersistentClient created in {t1 - t0:.2f}s")

    print("Step 3: Creating collection...")
    t0 = time.time()
    collection = client.get_or_create_collection(
        name="baby_feeding",
        embedding_function=embedding_function,
        metadata={"hnsw:space": "cosine"}
    )
    t1 = time.time()
    print(f"Step 3 done: Collection created in {t1 - t0:.2f}s")

    texts = []
    metadatas = []
    ids = []
    doc_ids = []

    print(f"Processing {len(documents)} documents...")
    for doc_idx, doc in enumerate(documents):
        chunks = split_document(doc['content'])
        for i, chunk in enumerate(chunks):
            texts.append(chunk['content'])
            metadatas.append({
                'category': doc['category'],
                'filename': doc['filename'],
                'filepath': doc['filepath'],
                'title': doc['title'],
                'section': chunk['section'],
                'parent_section': chunk.get('parent_section', ''),
                'topics': doc['topics'],
                'age_ranges': doc['age_ranges'],
                'authority': doc['authority'],
                'chunk_index': i,
                'total_chunks': len(chunks),
            })
            ids.append(f"{doc['filename']}_{i}")
            doc_ids.append(doc['filename'])

        if (doc_idx + 1) % 10 == 0:
            print(f"Processed {doc_idx + 1}/{len(documents)} documents, {len(texts)} chunks collected")

    print(f"Total chunks to add: {len(texts)}")

    batch_size = 100
    for i in range(0, len(texts), batch_size):
        end = min(i + batch_size, len(texts))
        batch_texts = texts[i:end]
        batch_metadatas = metadatas[i:end]
        batch_ids = ids[i:end]

        print(
            f"Adding batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size} ({len(batch_texts)} chunks)...")
        collection.add(
            documents=batch_texts,
            metadatas=batch_metadatas,
            ids=batch_ids
        )
        print(f"Batch {i // batch_size + 1} added, current count: {collection.count()}")

    print(f"已加载 {len(texts)} 个文档块到 Chroma")
    print(f"覆盖 {len(set(doc_ids))} 个文档")

    stats_count = collection.count()
    print(f"向量数据库统计: {stats_count} 条记录")

    summary = {
        'total_documents': len(set(doc_ids)),
        'total_chunks': len(texts),
        'categories': list(set([m['category'] for m in metadatas])),
        'topics': list(set([t for m in metadatas for t in m['topics']])),
        'age_ranges': list(set([a for m in metadatas for a in m['age_ranges']])),
    }

    summary_path = CHROMA_DB_DIR / 'db_summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"数据库摘要已保存: {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    print("=== 加载 RAG 知识库 ===")
    print(f"数据目录: {RAG_DATA_DIR}")
    print(f"Chroma 数据库目录: {CHROMA_DB_DIR}")

    documents = load_markdown_files()
    print(f"\n找到 {len(documents)} 个文档")

    if not documents:
        print("没有找到文档，请先运行爬虫脚本")
        return

    print("\n初始化 text2vec 模型...")
    print("\n初始化 Chroma 向量数据库...")
    init_chroma_db(documents)

    print("\n=== 知识库加载完成 ===")


if __name__ == '__main__':
    main()
