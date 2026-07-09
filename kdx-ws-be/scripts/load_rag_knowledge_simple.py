#!/usr/bin/env python3
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

RAG_DATA_DIR = Path('/home/konglingwen/Desktop/myspace/kdx/kdx-ws-be/data/rag/baby_feeding')
CHROMA_DB_DIR = Path('/home/konglingwen/Desktop/myspace/kdx/kdx-ws-be/data/chroma_db')

def log(msg):
    print(msg)
    sys.stdout.flush()

log('Step 1: Loading embedding function...')
from app.scripts.text2vec_embedding import Text2VecEmbeddingFunction
ef = Text2VecEmbeddingFunction()
log(f'Embedding function created')

dim = len(ef._encode('测试'))
log(f'Embedding dimension: {dim}')

log('\nStep 2: Creating ChromaDB...')
from chromadb import PersistentClient
client = PersistentClient(path=str(CHROMA_DB_DIR))
collection = client.create_collection(
    name='baby_feeding',
    embedding_function=ef,
    metadata={'hnsw:space': 'cosine'}
)
log('ChromaDB collection created')

log('\nStep 3: Loading documents...')
documents = []
for category in os.listdir(RAG_DATA_DIR):
    category_path = RAG_DATA_DIR / category
    if os.path.isdir(category_path) and category != '__pycache__':
        for filename in os.listdir(category_path):
            if filename.endswith('.md') and filename != 'Untitled.md':
                filepath = category_path / filename
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                documents.append({
                    'category': category,
                    'filename': filename,
                    'content': content,
                    'title': filename.replace('.md', '')
                })

log(f'Loaded {len(documents)} documents')

log('\nStep 4: Splitting documents...')
texts = []
metadatas = []
ids = []

for doc_idx, doc in enumerate(documents):
    content = doc['content']
    chunks = [content[i:i+500] for i in range(0, len(content), 450)]
    for i, chunk in enumerate(chunks):
        if len(chunk) >= 50:
            texts.append(chunk)
            metadatas.append({
                'category': doc['category'],
                'filename': doc['filename'],
                'title': doc['title'],
                'chunk_index': i
            })
            ids.append(f'{doc["filename"]}_{i}')
    
    if (doc_idx + 1) % 20 == 0:
        log(f'Processed {doc_idx + 1}/{len(documents)} documents, {len(texts)} chunks')

log(f'Total chunks: {len(texts)}')

log('\nStep 5: Adding to ChromaDB...')
batch_size = 100
for i in range(0, len(texts), batch_size):
    end = min(i + batch_size, len(texts))
    collection.add(
        documents=texts[i:end],
        metadatas=metadatas[i:end],
        ids=ids[i:end]
    )
    log(f'Added batch {i//batch_size + 1}/{(len(texts)+batch_size-1)//batch_size}')

log(f'\nFinal count: {collection.count()}')

summary = {
    'total_documents': len(documents),
    'total_chunks': len(texts),
    'categories': list(set([m['category'] for m in metadatas]))
}
with open(CHROMA_DB_DIR / 'db_summary.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

log('Done!')
