#!/usr/bin/env python3
"""
测试 RAG 知识库查询功能
使用 text2vec-base-chinese 作为 Embedding 模型
"""

from pathlib import Path
from chromadb import PersistentClient
from text2vec_embedding import Text2VecEmbeddingFunction

CHROMA_DB_DIR = Path(__file__).parent.parent / 'data' / 'chroma_db'

_embedding_function = None

def get_embedding_function():
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = Text2VecEmbeddingFunction()
    return _embedding_function

def query_knowledge(query, n_results=3):
    embedding_function = get_embedding_function()
    client = PersistentClient(path=str(CHROMA_DB_DIR))
    collection = client.get_collection(
        name="baby_feeding",
        embedding_function=embedding_function
    )
    
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    return results

def main():
    print("=== RAG 知识库查询测试 ===")
    
    test_queries = [
        "婴儿什么时候开始添加辅食",
        "母乳喂养的好处",
        "如何预防婴儿腹泻",
        "辅食添加原则",
        "婴儿睡眠安全注意事项"
    ]
    
    for query in test_queries:
        print(f"\n查询: {query}")
        print("-" * 60)
        
        results = query_knowledge(query)
        
        for i, (doc, meta, dist) in enumerate(zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        )):
            print(f"\n结果 {i+1}:")
            print(f"来源: {meta['filename']}")
            print(f"相似度: {1-dist:.4f}")
            print(f"内容:\n{doc[:200]}...")

if __name__ == '__main__':
    main()
