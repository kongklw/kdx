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

def split_document_by_section(content, chunk_size=500, chunk_overlap=50):
    sections = re.split(r'(^##\s+.+)', content, flags=re.MULTILINE)
    
    chunks = []
    current_chunk = ''
    current_section = ''
    
    for i, part in enumerate(sections):
        if part.startswith('## '):
            if current_chunk.strip():
                chunks.append({
                    'content': current_chunk.strip(),
                    'section': current_section
                })
            current_section = part[3:].strip()
            current_chunk = part + '\n'
        else:
            sentences = part.split('\n')
            for sentence in sentences:
                if len(current_chunk) + len(sentence) <= chunk_size:
                    current_chunk += sentence + '\n'
                else:
                    if current_chunk.strip():
                        chunks.append({
                            'content': current_chunk.strip(),
                            'section': current_section
                        })
                    current_chunk = sentence + '\n'
    
    if current_chunk.strip():
        chunks.append({
            'content': current_chunk.strip(),
            'section': current_section
        })
    
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
    from chromadb import PersistentClient
    from text2vec_embedding import Text2VecEmbeddingFunction
    
    embedding_function = Text2VecEmbeddingFunction()
    
    if CHROMA_DB_DIR.exists():
        shutil.rmtree(CHROMA_DB_DIR)
    
    client = PersistentClient(path=str(CHROMA_DB_DIR))
    
    collection = client.get_or_create_collection(
        name="baby_feeding",
        embedding_function=embedding_function,
        metadata={
            "hnsw:space": "cosine",
            "hnsw:ef_construction": 128,
            "hnsw:M": 16,
        }
    )
    
    texts = []
    metadatas = []
    ids = []
    doc_ids = []
    
    for doc in documents:
        chunks = split_document(doc['content'])
        for i, chunk in enumerate(chunks):
            texts.append(chunk['content'])
            metadatas.append({
                'category': doc['category'],
                'filename': doc['filename'],
                'filepath': doc['filepath'],
                'title': doc['title'],
                'section': chunk['section'],
                'topics': doc['topics'],
                'age_ranges': doc['age_ranges'],
                'authority': doc['authority'],
                'chunk_index': i,
                'total_chunks': len(chunks),
            })
            ids.append(f"{doc['filename']}_{i}")
            doc_ids.append(doc['filename'])
    
    collection.add(
        documents=texts,
        metadatas=metadatas,
        ids=ids
    )
    
    print(f"已加载 {len(texts)} 个文档块到 Chroma")
    print(f"覆盖 {len(set(doc_ids))} 个文档")
    
    stats = collection.get()
    print(f"向量数据库统计: {stats['count']} 条记录")
    
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