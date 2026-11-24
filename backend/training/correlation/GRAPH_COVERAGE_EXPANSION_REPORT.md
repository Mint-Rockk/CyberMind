# Graph Coverage Expansion Report

## Pre-change audit

The audit was performed before any new synchronization writes.

| Measure | Result |
|---|---:|
| Usable normalized reports | 12,095 |
| Reports with extracted entities | 8,427 |
| Reports without extracted entities | 3,668 |
| Reports with provenance | 12,095 |
| PostgreSQL documents | 28 |
| PostgreSQL documents with entities | 28 |
| Neo4j `ThreatReport` nodes | 28 |
| Graph-covered reports | 28 |
| Graph coverage of usable reports | 0.2315% |
| Synced graph states | 28 |
| Failed/rejected graph states | 0 |

The gap is not caused by Neo4j rejection. The relational ingestion store was
populated only with the earlier controlled 28-report sample; the remaining
12,067 normalized reports had never been persisted as `CTIDocument` records
and therefore had no document IDs for the existing
`POST /api/v1/graph/sync/documents/{document_id}` endpoint.

All 12,095 normalized records contain a stable dataset report ID, source
provenance, and non-empty normalized text. Reports without extracted entities
are still eligible for a provenance-backed `ThreatReport`/`Source` projection,
but they cannot produce evidence-backed entity relationships. No invalid or
unresolved entity identifiers were found in the normalized JSONL inventory;
the pre-change failure category is “not persisted”, not “rejected by graph
synchronization”.

## Existing synchronization path

The expansion uses the existing services without a second graph writer:

1. `normalize_record` creates the canonical normalized document and provenance.
2. `persist_document_entities` runs the existing deterministic extractor and
   creates stable relational entity associations with evidence.
3. `GraphSynchronizer.sync_document` performs the existing retrying,
   `MERGE`-based Neo4j projection.
4. `GraphSyncState` records resumable per-document status and failures.

The dataset driver is an orchestration wrapper only. It supports dry-run,
bounded batches, resumable processing, and a repeat of an already-synced
batch for idempotency verification. It does not issue ad-hoc Cypher and does
not infer campaign relationships.

## Preflight controls

- Neo4j authentication and `RETURN 1 AS ok` were verified.
- Stable IDs and `MERGE` behavior were verified by the existing live
  integration test.
- Provenance/evidence retention was verified by the existing graph tests.
- Retry behavior is provided by `GraphSynchronizer`.
- Dry-run performs validation and reports planned work without database writes.

## Coverage verification procedure

Each controlled batch was followed by Neo4j count/provenance checks, and the
failed record was retried individually before a final idempotency resync.

## Completed controlled expansion

The existing pipeline processed 12,095 reports in 25 resumable batches,
with one malformed source record retried after the shared normalization path
removed PostgreSQL-incompatible NUL bytes. The retry succeeded and a resync
of that exact report produced no duplicate nodes or relationships.

| Measure | Final result |
|---|---:|
| Neo4j `ThreatReport` nodes | 12,095 |
| Reports with provenance | 12,095 |
| Reports linked to at least one entity | 8,317 |
| `MENTIONS` relationships | 83,288 |
| `REPORTED_BY` relationships | 12,095 |
| `Campaign` nodes | 1,039 |
| Direct report-to-campaign relationships | 0 |
| Failed final reports | 0 |

The graph contains evidence-backed entity mentions only. No campaign
relationship was inferred from shared actors or malware, and no unsupported
relationship type was created. The one rejected record was a persistence
encoding failure, not a graph rejection; its source content was preserved
with NUL bytes removed only for database-safe serialization.
