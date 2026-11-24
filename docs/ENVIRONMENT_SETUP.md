# CyberMind Environment Setup

Copy `.env.example` to `.env`; `.env` is ignored and must never be committed.
Key settings are `DATABASE_URL`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
`NEO4J_AUTH`, `NEO4J_DATABASE`, `NEO4J_*_PORT`, `QDRANT_*`, `GENAI_*`,
`NVD_API_KEY`, and `CORRELATION_*`.

Neo4j is local-only by default and uses Bolt at `bolt://localhost:7687`.
See [backend/training/correlation/NEO4J_SETUP.md](../backend/training/correlation/NEO4J_SETUP.md)
for startup, health, schema, ingestion, and troubleshooting instructions.

The CyberMind demo defaults to `CORRELATION_PREDICTOR=trained_evidence`, loading the
saved f1-improvement-v3 Random Forest (12 inputs, threshold 0.35) without retraining.
Set `CORRELATION_PREDICTOR=baseline` to explicitly use the six-feature heuristic.
Trained predictor loading failures are reported explicitly and never fall back to
baseline.