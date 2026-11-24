# Knowledge-graph integration status

## Implemented

- Neo4j Community Edition is configured in
  `infrastructure\docker-compose.yml` with a pinned `5.26.5-community` image,
  localhost-only Bolt/Browser bindings, health checking, and persistent named
  volumes.
- The backend uses Neo4j driver `5.28.8` over Bolt and verifies both driver
  connectivity and a query against the configured database.
- Graph writes use stable identifiers and `MERGE`, retain provenance/evidence
  metadata, and are tracked by PostgreSQL graph synchronization state.
- The existing graph projection supports reports, sources, threat actors,
  campaigns, malware, tools, indicators, vulnerabilities, ATT&CK techniques,
  and sectors.
- The canonical `correlation-features-v1` six-feature schema and silver labels
  are unchanged. Knowledge-graph similarity remains the existing set-based
  Jaccard implementation with explicit missing-data availability.

## Controlled verification

The opt-in test `backend\tests\test_neo4j_integration.py` performs an
idempotent, evidence-backed report-to-threat-actor round trip using uniquely
named integration nodes, checks provenance and relationship evidence, then
removes only those test nodes. It is skipped unless
`CYBERMIND_NEO4J_INTEGRATION=1` is set and is not a dataset ingestion job.

Live verification completed in this environment after starting Docker Desktop:

- Neo4j `5.26.5-community` container reported healthy.
- Authenticated Bolt `RETURN 1 AS ok` returned `1`.
- `/api/v1/health` and `/api/v1/graph/status` reported `connected`.
- Wrong credentials were classified as `authentication_failure`.
- The controlled round trip passed, including idempotency and provenance/evidence
  retrieval.

The unit tests cover an established relationship, missing graph data, shared
actor names without a shared relationship, and lookup/representation failures.
Missing graph evidence is explicit and is not silently treated as a confirmed
relationship.

## Actual CTI projection

All 12,095 normalized CTI-EACL24 reports were routed through the existing
normalization, extraction, persistence, and graph synchronization pipeline.
They produced 12,095 `ThreatReport` nodes, 83,288 evidence-backed `MENTIONS`
relationships, and 12,095 provenance-backed `REPORTED_BY` relationships.
The final retry/resynchronization was idempotent and preserved evidence and
provenance. Full expansion details are in
[GRAPH_COVERAGE_EXPANSION_REPORT.md](./GRAPH_COVERAGE_EXPANSION_REPORT.md).

No ATT&CK mappings or direct campaign associations were present in this sample,
and no such relationships were fabricated.

## Dataset-readiness boundary

Neo4j is operational and covers all 12,095 reports used by the correlation
dataset. The v3 graph feature was recomputed from this projection; genuine
empty relationships are distinct from unavailable lookups. Qdrant remains a
separate unavailable dependency. See
[DATASET_READINESS_V3.md](./DATASET_READINESS_V3.md).
