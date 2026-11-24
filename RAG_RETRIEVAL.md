# Hybrid RAG retrieval

CyberMind's retrieval layer assembles evidence; it does not generate or infer an
answer. `POST /api/v1/rag/retrieve` returns ranked evidence, a context string,
source references, and an explicit `sufficient_evidence` flag.

## Retrieval sources

The service combines:

- Qdrant semantic chunks from normalized CTI documents.
- PostgreSQL document metadata and normalized text.
- Extracted entities and document evidence spans.
- MITRE ATT&CK techniques and document mappings.
- Stored correlation records and explanations.
- Campaign associations and evidence.
- Predefined Neo4j graph node searches.

NVD/CVE and other source categories are represented through their persisted
documents/entities and retain the original source URL and source reliability.

## Provenance and ranking

Every evidence item includes its evidence type, score, document ID when linked,
title, source URL, chunk ID when semantic, relevant text, publication timestamp,
source reliability when known, and retriever-specific provenance. Duplicate
passages are collapsed by document and normalized text, retaining the strongest
ranked item. Results are then sorted by score and limited by the request.

Metadata filters are applied to semantic Qdrant retrieval and structured
PostgreSQL documents: source, publication date range, document type, and entity.
Stored correlations also accept a minimum probability threshold.

If all configured sources are unavailable or no evidence matches, the response
returns an empty context, `sufficient_evidence: false`, and warnings such as
`semantic_retrieval_unavailable`, `graph_retrieval_unavailable`, or
`insufficient_evidence`. The service never fabricates a passage or citation.

Example request:

```json
{
  "query": "ransomware targeting hospitals",
  "document_type": "advisory",
  "minimum_correlation_probability": 0.7,
  "limit": 8
}
```
