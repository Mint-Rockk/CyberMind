from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from qdrant_client import QdrantClient, models

from app.vector_store.chunking import DocumentChunk, split_document
from app.vector_store.embeddings import SentenceEmbeddingService


@dataclass(frozen=True)
class SemanticSearchResult:
    document_id: UUID
    chunk_id: str
    score: float
    text: str
    metadata: dict[str, Any]


def _epoch(value: datetime | None) -> float | None:
    return value.timestamp() if value else None


class QdrantSemanticIndex:
    def __init__(
        self,
        client: QdrantClient,
        embedder: SentenceEmbeddingService,
        *,
        collection_name: str,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.collection_name = collection_name
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def ensure_collection(self) -> None:
        collections = self.client.get_collections().collections
        if any(collection.name == self.collection_name for collection in collections):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=self.embedder.expected_dimension,
                distance=models.Distance.COSINE,
            ),
        )

    def index_document(
        self,
        *,
        document_id: UUID,
        text: str,
        source_id: UUID,
        source_url: str,
        title: str,
        collected_at: datetime,
        published_at: datetime | None,
        document_type: str,
        source_reliability: float | None = None,
        entity_values: Iterable[str] = (),
    ) -> int:
        chunks = split_document(
            document_id,
            text,
            max_characters=self.chunk_size,
            overlap_characters=self.chunk_overlap,
        )
        self.ensure_collection()
        self.delete_document(document_id)
        if not chunks:
            return 0
        vectors = self.embedder.encode([chunk.text for chunk in chunks])
        points = [
            models.PointStruct(
                id=chunk.chunk_id,
                vector=vector,
                payload={
                    "document_id": str(document_id),
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.index,
                    "text": chunk.text,
                    "source_id": str(source_id),
                    "source_url": source_url,
                    "title": title,
                    "collected_at": collected_at.isoformat(),
                    "collected_at_epoch": collected_at.timestamp(),
                    "published_at": published_at.isoformat() if published_at else None,
                    "published_at_epoch": _epoch(published_at),
                    "document_type": document_type,
                    "source_reliability": source_reliability,
                    "entity_values": list(entity_values),
                    "embedding_model": self.embedder.model_version,
                    "embedding_dimension": self.embedder.expected_dimension,
                    "preprocessing_version": "whitespace-normalized-v1",
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        return len(points)

    def delete_document(self, document_id: UUID) -> None:
        self.ensure_collection()
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=str(document_id)),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def search(
        self,
        query: str,
        *,
        source_id: UUID | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
        document_type: str | None = None,
        entity: str | None = None,
        limit: int = 10,
    ) -> list[SemanticSearchResult]:
        if not query.strip():
            raise ValueError("Semantic search query cannot be empty")
        self.ensure_collection()
        conditions: list[models.FieldCondition | models.Range] = []
        if source_id:
            conditions.append(
                models.FieldCondition(
                    key="source_id",
                    match=models.MatchValue(value=str(source_id)),
                )
            )
        if document_type:
            conditions.append(
                models.FieldCondition(
                    key="document_type",
                    match=models.MatchValue(value=document_type),
                )
            )
        if entity:
            conditions.append(
                models.FieldCondition(
                    key="entity_values",
                    match=models.MatchValue(value=entity),
                )
            )
        if published_after or published_before:
            conditions.append(
                models.FieldCondition(
                    key="published_at_epoch",
                    range=models.Range(
                        gte=_epoch(published_after),
                        lte=_epoch(published_before),
                    ),
                )
            )
        query_filter = models.Filter(must=conditions) if conditions else None
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=self.embedder.encode([query])[0],
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return [
            SemanticSearchResult(
                document_id=UUID(str(point.payload["document_id"])),
                chunk_id=str(point.payload["chunk_id"]),
                score=float(point.score),
                text=str(point.payload["text"]),
                metadata=dict(point.payload),
            )
            for point in response.points
        ]


class SemanticRetrievalService:
    """Shared retrieval facade for search, related-document discovery, and RAG."""

    def __init__(self, index: QdrantSemanticIndex) -> None:
        self.index = index

    def search(self, query: str, **filters: Any) -> list[SemanticSearchResult]:
        return self.index.search(query, **filters)

    def related_documents(
        self,
        query: str,
        *,
        limit: int = 10,
        **filters: Any,
    ) -> list[SemanticSearchResult]:
        return self.index.search(query, limit=limit, **filters)

    def neighbor_index(
        self,
        documents: Iterable[tuple[UUID, str]],
        *,
        limit: int = 5,
    ) -> dict[UUID, set[UUID]]:
        neighbors: dict[UUID, set[UUID]] = {}
        for document_id, text in documents:
            neighbors[document_id] = {
                result.document_id
                for result in self.index.search(text, limit=limit + 1)
                if result.document_id != document_id
            }
        return neighbors
