from __future__ import annotations

import ollama
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector

from meeting_intelligence_engine.config import settings

_sparse_encoder: SparseTextEmbedding | None = None


def get_qdrant_client() -> QdrantClient:
    kwargs = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs)


def dense_embed(text: str) -> list[float]:
    return ollama.embed(model=settings.dense_model, input=text).embeddings[0]


def sparse_embed(text: str) -> SparseVector:
    global _sparse_encoder
    if _sparse_encoder is None:
        _sparse_encoder = SparseTextEmbedding(model_name=settings.sparse_model)
    result = list(_sparse_encoder.embed([text]))[0]
    return SparseVector(indices=result.indices.tolist(), values=result.values.tolist())
