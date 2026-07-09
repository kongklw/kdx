#!/usr/bin/env python3
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

def log(msg):
    print(f'[TEST] {msg}')
    sys.stdout.flush()

log('=== RAG 查询测试 ===')

log('\n1. 测试路径计算')
current_file = Path(__file__).resolve()
log(f'当前脚本路径: {current_file}')
log(f'项目根目录: {current_file.parent.parent}')

chroma_db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'chroma_db')
log(f'chroma_db 路径: {chroma_db_path}')
log(f'chroma_db 目录存在: {os.path.exists(chroma_db_path)}')

log('\n2. 测试嵌入函数加载')
from app.scripts.text2vec_embedding import Text2VecEmbeddingFunction
ef = Text2VecEmbeddingFunction()
log(f'嵌入函数名称: {ef.name()}')
test_embed = ef._encode('测试')
log(f'嵌入维度: {len(test_embed)}')

log('\n3. 测试 ChromaDB 连接')
from chromadb import PersistentClient
client = PersistentClient(path=chroma_db_path)
collections = client.list_collections()
log(f'可用集合: {[c.name for c in collections]}')

collection = client.get_collection('baby_feeding')
log(f'集合记录数: {collection.count()}')

log('\n4. 测试查询 - 模拟 rag_query.py 的 retrieve_node')
query = '婴儿睡眠'
log(f'查询词: {query}')

query_embedding = ef.embed_query(query)
log(f'查询向量维度: {len(query_embedding[0])}')

results = collection.query(query_embeddings=query_embedding, n_results=3)
log(f'查询结果数: {len(results["documents"][0])}')

if len(results['documents'][0]) > 0:
    for i, doc in enumerate(results['documents'][0]):
        meta = results['metadatas'][0][i]
        distance = results['distances'][0][i] if results.get('distances') else None
        log(f'\n文档 {i+1}:')
        log(f'  标题: {meta.get("title", "N/A")}')
        log(f'  分类: {meta.get("category", "N/A")}')
        log(f'  相似度: {1 - distance:.4f}' if distance else '  相似度: N/A')
        log(f'  内容预览: {doc[:100]}...')
else:
    log('查询结果为空！')

log('\n5. 测试 rag_query.py 中的实际函数')
from app.ws.rag_query import get_embedding_function, get_chroma_collection

log('调用 get_chroma_collection()...')
try:
    rag_collection = get_chroma_collection()
    log(f'rag_collection.count(): {rag_collection.count()}')
except Exception as e:
    log(f'get_chroma_collection 失败: {e}')

log('调用 get_embedding_function()...')
try:
    rag_ef = get_embedding_function()
    rag_embed = rag_ef.embed_query('婴儿睡眠')
    log(f'rag_ef 嵌入维度: {len(rag_embed[0])}')
except Exception as e:
    log(f'get_embedding_function 失败: {e}')

log('\n6. 使用 rag_query.py 的函数进行查询')
try:
    rag_results = rag_collection.query(query_embeddings=rag_embed, n_results=3)
    log(f'rag_results 文档数: {len(rag_results["documents"][0])}')
    if len(rag_results['documents'][0]) > 0:
        for i, doc in enumerate(rag_results['documents'][0]):
            meta = rag_results['metadatas'][0][i]
            distance = rag_results['distances'][0][i] if rag_results.get('distances') else None
            log(f'文档 {i+1}: {meta.get("title")}, 相似度: {1 - distance:.4f}' if distance else '')
    else:
        log('rag_query.py 查询结果为空！')
except Exception as e:
    log(f'查询失败: {e}')

log('\n=== 测试完成 ===')
