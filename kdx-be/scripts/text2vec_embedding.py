#!/usr/bin/env python3
"""
适配 text2vec-base-chinese 的自定义 EmbeddingFunction
直接使用 transformers 库加载本地模型文件
"""

from typing import List
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

class Text2VecEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str = 'shibing624/text2vec-base-chinese'):
        from transformers import AutoTokenizer, AutoModel
        import torch
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        self.model.eval()
        self._model_name = model_name
    
    def __call__(self, input: Documents) -> Embeddings:
        return self.embed_documents(input)
    
    def embed_documents(self, texts: Documents) -> Embeddings:
        if isinstance(texts, str):
            texts = [texts]
        embeddings = []
        for text in texts:
            embedding = self._encode(text)
            embeddings.append(embedding)
        return embeddings
    
    def embed_query(self, input: str) -> Embeddings:
        return [self._encode(input)]
    
    def _encode(self, text: str) -> List[float]:
        import torch
        encoded_input = self.tokenizer(
            text,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors='pt'
        ).to(self.device)
        
        with torch.no_grad():
            model_output = self.model(**encoded_input)
            embeddings = model_output[0][:, 0, :]
        
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        
        return embeddings.cpu().numpy().tolist()[0]
    
    def name(self) -> str:
        return f"text2vec-{self._model_name}"
    
    def __str__(self):
        return self.name
