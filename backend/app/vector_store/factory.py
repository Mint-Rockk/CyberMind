from functools import lru_cache

from qdrant_client import QdrantClient

from app.core.config import get_settings
from app.vector_store.embeddings import SentenceEmbeddingService
from app.vector_store.qdrant import QdrantSemanticIndex


@lru_cache
def get_semantic_index() -> QdrantSemanticIndex:
    settings = get_settings()
    return QdrantSemanticIndex(
        QdrantClient(url=settings.qdrant_url, timeout=settings.qdrant_timeout),
        SentenceEmbeddingService(
            settings.embedding_model_name,
            model_version=settings.embedding_model_version,
            expected_dimension=settings.embedding_dimension,
            batch_size=settings.embedding_batch_size,
        ),
        collection_name=settings.qdrant_collection,
        chunk_size=settings.embedding_chunk_size,
        chunk_overlap=settings.embedding_chunk_overlap,
    )
