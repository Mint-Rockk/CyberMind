from datetime import datetime, timezone
from uuid import uuid4

from qdrant_client import QdrantClient

from app.vector_store.chunking import split_document
from app.vector_store.qdrant import QdrantSemanticIndex


class FakeEmbedder:
    expected_dimension = 3
    model_version = "test-embedding-v1"

    def encode(self, texts):
        return [
            [float(len(text)), float(index), 1.0]
            for index, text in enumerate(texts)
        ]


def test_chunking_is_bounded_and_stable():
    document_id = uuid4()
    chunks = split_document(document_id, "Sentence one. " * 100, max_characters=80, overlap_characters=10)

    assert chunks
    assert all(len(chunk.text) <= 80 for chunk in chunks)
    assert [chunk.chunk_id for chunk in chunks] == [
        chunk.chunk_id for chunk in split_document(
            document_id, "Sentence one. " * 100, max_characters=80, overlap_characters=10
        )
    ]


def test_qdrant_index_retrieval_filters_and_reindexing():
    client = QdrantClient(":memory:")
    index = QdrantSemanticIndex(
        client,
        FakeEmbedder(),
        collection_name="test_documents",
        chunk_size=100,
        chunk_overlap=10,
    )
    document_id = uuid4()
    source_id = uuid4()
    collected = datetime(2026, 11, 16, tzinfo=timezone.utc)

    assert index.index_document(
        document_id=document_id,
        text="Ransomware operations target healthcare organizations.",
        source_id=source_id,
        source_url="https://example.test/report",
        title="Ransomware report",
        collected_at=collected,
        published_at=collected,
        document_type="advisory",
        entity_values=["example-malware"],
    ) == 1
    results = index.search("ransomware", source_id=source_id, entity="example-malware")
    assert len(results) == 1
    assert results[0].document_id == document_id
    assert results[0].metadata["source_url"] == "https://example.test/report"
    assert results[0].metadata["embedding_model"] == "test-embedding-v1"

    assert index.index_document(
        document_id=document_id,
        text="Updated report content.",
        source_id=source_id,
        source_url="https://example.test/report",
        title="Updated report",
        collected_at=collected,
        published_at=collected,
        document_type="advisory",
        entity_values=["updated-malware"],
    ) == 1
    assert index.search("updated", entity="updated-malware")
    assert not index.search("ransomware", entity="example-malware")

    index.delete_document(document_id)
    assert not index.search("updated")
