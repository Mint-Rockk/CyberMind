# CyberMind

CyberMind is a GenAI-powered external-source Cyber Threat Intelligence platform. The current implementation includes lawful CTI collection, raw-record preservation, document normalization/deduplication, deterministic entity extraction, explainable document classification/prioritization, correlation and campaign workflows, an evidence-backed Neo4j graph projection/explorer, Qdrant semantic document indexing/search, provenance-preserving hybrid RAG retrieval, grounded investigations, assistant conversations, reports, and analyst review.

## Prerequisites

- Python 3.11 or newer
- Node.js 20.19 or newer
- npm
- Docker Desktop with the Docker daemon running for local services

The currently inspected environment has Python 3.13.7, Node.js v22.17.0, npm 10.9.2, Git 2.51.0, and Docker CLI 29.4.1. See [DEPENDENCIES.md](./DEPENDENCIES.md) for the full inventory.

## Backend

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run_server.py
```

Health endpoint: <http://127.0.0.1:8000/api/v1/health>

The local fictional CTI demonstration, source seeding, feed URLs, and end-to-end
collection instructions are documented in [docs/LOCAL_DEMO.md](docs/LOCAL_DEMO.md).

## Frontend

```powershell
Set-Location frontend
npm ci
npm run dev
```

The frontend runs at <http://localhost:5173> and displays backend connectivity through the health endpoint.

For exact environment, deployment, API, schema, and testing procedures, see
[docs/ENVIRONMENT_SETUP.md](docs/ENVIRONMENT_SETUP.md),
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), [docs/API.md](docs/API.md),
[docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md), and
[docs/TESTING.md](docs/TESTING.md).

## Local infrastructure

Start PostgreSQL, Neo4j, and Qdrant after Docker Desktop is running:

```powershell
docker compose -f infrastructure\docker-compose.yml up -d
docker compose -f infrastructure\docker-compose.yml ps
```

Copy `.env.example` to `.env` and adjust values for local development. Do not commit `.env` or credentials.
The baseline predictor remains available. The saved `f1-improvement-v3` evidence-aware
Random Forest is used for demo-source correlations with its own persisted feature order
and selected threshold; no model is retrained by the demo.

## Database migrations

After the PostgreSQL service is healthy:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

The migration creates the schema and graph synchronization state only; it does not insert fabricated production data.

## Public CTI connectors

Sources are configured through the source API and must point to lawful public endpoints. Supported connector types are `nvd`, `mitre_attack`, `rss`, `taxii`, `advisory`, `osint`, and `research`. Connector configuration supports timeout, retry, rate-limit, response-path, and schedule settings; scheduled collection uses `schedule_minutes`.

NVD's public API can be used without credentials at a lower rate. For higher public API rate limits, request an API key from <https://nvd.nist.gov/developers/request-an-api-key>, set `NVD_API_KEY` in the local `.env`, and configure no secret directly in a source record. The key is never hardcoded or committed.

The collection layer stores raw payloads and source references before creating normalized CTI documents. Fixture data in tests is explicitly labeled as fixture data and is never presented as live intelligence.

Entity extraction uses deterministic regex patterns, curated threat-intelligence aliases, and structured source metadata. Extracted entities are normalized by type, linked to source documents, and retain evidence text/spans, confidence, extraction method, and UTC extraction timestamps. No custom NLP model is trained or fabricated.

Document classification uses `rule_based_v1` category rules and stores supporting keywords. Prioritization uses `weighted_factors_v1` with visible severity, recency, source reliability, information confidence, independent corroboration, and campaign relevance factors; source reliability and information confidence are never combined into an opaque value.

## Document normalization

Ingestion preserves the original connector content in `RawSourceRecord`, then stores UTC timestamps, cleaned text, normalized metadata, SHA-256 content hashes, and exact/near-duplicate relationships on `CTIDocument`. Near duplicates use a RapidFuzz ratio threshold of 92; every source record remains persisted so provenance is not discarded.

## Validation

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest
Set-Location ..\frontend
npm run build
```

See [ARCHITECTURE.md](./ARCHITECTURE.md), [DEVELOPMENT_ROADMAP.md](./DEVELOPMENT_ROADMAP.md), and [PROJECT_CHECKLIST.md](./PROJECT_CHECKLIST.md) for scope and planned implementation.
See [SEMANTIC_INDEXING.md](./SEMANTIC_INDEXING.md) for the embedding, chunking, metadata, filtering, and re-indexing contract.
See [RAG_RETRIEVAL.md](./RAG_RETRIEVAL.md) for hybrid evidence retrieval, ranking, provenance, and insufficiency behavior.
