#!/usr/bin/env python3
"""
适配 text2vec-base-chinese 的自定义 EmbeddingFunction
使用 text2vec 库加载模型，轻量级实现
"""

from typing import List
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class Text2VecEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str = 'shibing624/text2vec-base-chinese'):
        from text2vec import SentenceModel

        self.model = SentenceModel(model_name)
        self._model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        return self.embed_documents(input)

    def embed_documents(self, texts: Documents) -> Embeddings:
        if isinstance(texts, str):
            texts = [texts]
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, input: str) -> Embeddings:
        embedding = self.model.encode([input], normalize_embeddings=True)
        return embedding.tolist()

    def name(self) -> str:
        return f"text2vec-{self._model_name}"

    def __str__(self):
        return self.name