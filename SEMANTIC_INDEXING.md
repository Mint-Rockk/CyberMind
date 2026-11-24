# Semantic document indexing

CyberMind indexes normalized CTI text in Qdrant using the pretrained
`sentence-transformers/all-MiniLM-L6-v2` model. No embedding model is trained or
fine-tuned by the application.

## Contract

| Setting | Default | Meaning |
|---|---|---|
| `QDRANT_COLLECTION` | `cti_documents_v1` | Versioned Qdrant collection |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | Hugging Face model identifier |
| `EMBEDDING_MODEL_VERSION` | `all-MiniLM-L6-v2` | Metadata version recorded with every chunk |
| `EMBEDDING_DIMENSION` | `384` | Expected vector dimension |
| `EMBEDDING_CHUNK_SIZE` | `1200` | Maximum chunk characters |
| `EMBEDDING_CHUNK_OVERLAP` | `150` | Overlap between adjacent chunks |
| `EMBEDDING_BATCH_SIZE` | `32` | Sentence Transformer encoding batch size |

Text is whitespace-normalized, split at sentence boundaries, and split into
bounded character windows for unusually long sentences. Each chunk has a
deterministic UUID-based point ID derived from document ID, index, and content.

Every payload preserves the document ID, chunk ID, chunk index, text, source ID,
source URL, title, collection/publication timestamps, document type, entity
values, model version, dimension, and preprocessing version.

## Operations

- `POST /api/v1/vector/documents/{document_id}/index` creates or replaces all
  chunks for a document.
- `DELETE /api/v1/vector/documents/{document_id}` removes all document chunks.
- `GET /api/v1/vector/search` performs semantic search with optional source,
  publication date, document type, and entity filters.

The same `SemanticRetrievalService` is the shared boundary for semantic search,
related-document discovery, RAG retrieval, and optional semantic candidate
generation. Qdrant remains rebuildable from PostgreSQL normalized documents.

Start Qdrant before using these operations:

```powershell
docker compose -f infrastructure\docker-compose.yml up -d qdrant
```

The embedding model is downloaded separately into the Hugging Face cache when
the embedding service is first loaded:

```powershell
backend\.venv\Scripts\python.exe -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
```
