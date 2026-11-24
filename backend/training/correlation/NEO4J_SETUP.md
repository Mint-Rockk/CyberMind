# Local Neo4j setup

CyberMind uses the Neo4j Python driver `5.28.8` (the dependency range is
`>=5.25,<6`) over Bolt. The supported local setup is Neo4j Community Edition
`5.26.5`, started by the existing Compose file.

## Configure and start

From `E:\genAI`:

```powershell
Copy-Item .env.example .env
# Edit .env and replace POSTGRES_PASSWORD, NEO4J_PASSWORD, and NEO4J_AUTH.
docker compose -f infrastructure\docker-compose.yml up -d neo4j
docker compose -f infrastructure\docker-compose.yml ps neo4j
```

Neo4j is bound to localhost only:

- Bolt: `bolt://localhost:7687`
- Browser: `http://localhost:7474`
- Database: `neo4j`

The credentials are read from `NEO4J_USER`, `NEO4J_PASSWORD`, and
`NEO4J_DATABASE`; Compose uses the matching `NEO4J_AUTH` value for first
initialization. Data and logs persist in the `neo4j_data` and `neo4j_logs`
named volumes. Do not commit `.env`.

Stop the service without deleting data:

```powershell
docker compose -f infrastructure\docker-compose.yml stop neo4j
```

## Verify

```powershell
docker compose -f infrastructure\docker-compose.yml ps neo4j
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_health.py tests\test_graph.py
$env:CYBERMIND_NEO4J_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest tests\test_neo4j_integration.py
```

The API health endpoint remains live even when Neo4j is down and reports the
graph status at `/api/v1/health` under `neo4j`. `/api/v1/graph/status` performs
an authenticated Bolt query against the configured database and distinguishes
`connected`, `unreachable`, `authentication_failure`, and
`invalid_configuration`.

## Schema and ingestion

The application projection is evidence-backed and uses stable IDs with
idempotent `MERGE` writes. It represents `ThreatReport`, `Source`,
`ThreatActor`, `Campaign`, `Malware`, `Tool`, `Indicator`, `Vulnerability`,
`ATTACKTechnique`, and `Sector` nodes. Relationships include `REPORTED_BY`,
`MENTIONS`, `USES_TECHNIQUE`, `PART_OF_CAMPAIGN`, and `RELATED_TO`; each
projection preserves the available evidence, provenance, timestamps, confidence,
relationship origin, and status.

Run a controlled projection only through the existing endpoint:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/graph/sync/documents/<document-uuid>
```

The PostgreSQL `graph_sync_states` table records attempts and failures.
Synchronizing the same document again is safe and does not create duplicate
nodes or relationships. Do not bulk re-ingest the dataset as part of setup.

## Troubleshooting

- If Compose cannot connect, start Docker Desktop and verify `docker info`.
- If the health status is `authentication_failure`, make `NEO4J_PASSWORD`
  and the `NEO4J_AUTH` password consistent. Existing named volumes retain the
  original password; changing it may require a deliberate local volume
  migration, not an automatic deletion.
- If the status is `unreachable`, verify that localhost port 7687 is free and
  that the Neo4j container is healthy.
- If the status is `invalid_configuration`, set all four `NEO4J_*` connection
  values in `.env`.
