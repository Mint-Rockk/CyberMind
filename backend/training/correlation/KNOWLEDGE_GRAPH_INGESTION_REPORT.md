# Controlled knowledge-graph ingestion report

## Scope and sample selection

The local PostgreSQL database was initialized with the existing Alembic
migrations and initially contained zero documents, entities, associations, or
graph-sync states. The source dataset
`backend/data/correlation/processed/normalized_reports.jsonl` contains 12,095
real CTI-EACL24 reports:

- 8,427 have extracted entities.
- 8,427 have normalized entity values.
- 12,095 have provenance metadata.
- 3,203 have explicit campaign references in the source dataset.
- 2,042 meet the controlled-sample eligibility filter: source URL, content,
  provenance, and at least three extracted entity types.

The sample contains 28 reports, four each from ESET, FireEye, Fortinet, IBM,
Kaspersky, McAfee, and Palo Alto Networks. No synthetic report or entity was
used.

Selected dataset report IDs and resulting PostgreSQL document IDs:

| Dataset report ID | Document ID | Source |
|---|---|---|
| `cti-eacl24-85f073ae9b4db041fce3caa4` | `7e3d2341-71fc-4167-bc52-694717948978` | ESET |
| `cti-eacl24-fb7ff5f6535eb1d424c735ac` | `4451663a-2749-4287-96da-a47f3c7e1119` | ESET |
| `cti-eacl24-496d67927479cd5d42e7d244` | `ff2f836a-32fa-4952-93c3-209099449728` | ESET |
| `cti-eacl24-47923493eab8193a39eb414a` | `7d8dfa70-02eb-4b8a-9dcf-00ad7bdf22b3` | ESET |
| `cti-eacl24-ec61cda61348144d7396eac9` | `6ff95c18-2173-4b44-95d6-8717b1135cf6` | FireEye |
| `cti-eacl24-4481eecfa26a8955766e72e2` | `6593a168-1a6c-4692-9f72-751cd78c74c3` | FireEye |
| `cti-eacl24-f49f3ae84ae34d6a0f19f456` | `82549f10-0162-4528-9cdd-251d420e0cf2` | FireEye |
| `cti-eacl24-14d1027f54415094effd9054` | `bbe28f44-9b7e-4cd5-b408-70bc81a208ee` | FireEye |
| `cti-eacl24-de65f13841dc0b10b41122d0` | `3a799d95-f8d4-458a-bbc9-0a986875fdb1` | Fortinet |
| `cti-eacl24-2ee80cbf936c2c22b2454d75` | `ee92ba80-bdcc-48a9-93e0-16d873f3f517` | Fortinet |
| `cti-eacl24-35dc8ce4cc449b127604b4a9` | `ec3972b3-cdeb-4cc8-b0af-1ea24a2ebb3a` | Fortinet |
| `cti-eacl24-d8358b09860b7addaebac8a1` | `2708ad92-27f7-49e1-9b07-186b38e92b12` | Fortinet |
| `cti-eacl24-2122e348c530865e7b1d7f2d` | `63be7b8b-b9dc-4bc6-8ecb-be8671c5dd28` | IBM |
| `cti-eacl24-aeddf339a976f1abde47dfc6` | `5cc0c3b6-e95c-4811-a69b-6cdac9d81255` | IBM |
| `cti-eacl24-d88fd2c905706d2e89223b2e` | `62e9202f-57af-454b-ac05-f0eda85f3262` | IBM |
| `cti-eacl24-d4847b86e79be8d8a1f30792` | `3adc9f38-97a4-4d9d-a337-a77596251ee4` | IBM |
| `cti-eacl24-4392f09e994b888a40f6ccfb` | `42d3e439-b419-46af-a608-ed4ecc8ab5d2` | Kaspersky |
| `cti-eacl24-dd8798f0e899e3b4a661254a` | `12e6978e-397f-4077-931d-3fc2caf640e8` | Kaspersky |
| `cti-eacl24-aaa0f5407307b34e90aabd07` | `1bd29f17-544e-4e40-8be9-8abb83d6ab71` | Kaspersky |
| `cti-eacl24-4acc7cd856f1940d1d2d3fdb` | `724d284f-1ab2-41fe-8f67-db43e88c7a03` | Kaspersky |
| `cti-eacl24-ff071649656ba3044bff3025` | `770a5d7d-7c48-417a-b351-d89fe1c49ea5` | McAfee |
| `cti-eacl24-53fcabddf79675110ecac1e7` | `c0c44b46-1a82-4d5a-87db-e3733a0421d0` | McAfee |
| `cti-eacl24-d72e580904eb6fad4248524d` | `4fa14ec9-a223-4884-8b7e-ed665ccd3872` | McAfee |
| `cti-eacl24-478be6043da42f1b8ceb44cb` | `c3e3e3c1-9d1b-4d08-b0f9-09877fe8f7b7` | McAfee |
| `cti-eacl24-07092ef80324a809d2b68dbe` | `12f46234-c0d8-4b74-9a12-9917ad2b436f` | Palo Alto |
| `cti-eacl24-2a0b8aa10d6ef73e0bf0baa1` | `7a359986-4565-4820-9d50-fff2f7fa7dd5` | Palo Alto |
| `cti-eacl24-d0890bc8d113720cfe35ff76` | `2a2302ba-f935-47d5-871f-3e67a5403c73` | Palo Alto |
| `cti-eacl24-961d6665889613399dabb9b2` | `ba1e2b7b-497a-408b-a522-8d873cc77a3f` | Palo Alto |

## Synchronization method

Each dataset record was converted to the existing `CollectedRecord` contract
and routed through `execute_ingestion_job`, which called the existing
normalization, entity extraction, classification, prioritization, and
PostgreSQL persistence services. No parallel document or entity schema was
created.

The existing service endpoint for graph projection is:

```text
POST /api/v1/graph/sync/documents/{document_id}
```

The controlled run invoked the same `GraphSynchronizer.sync_document` service
method for the 28 persisted document IDs. Before synchronization, all 28
`ThreatReport:<document_id>` stable IDs were absent from Neo4j.

The first attempt exposed an existing defect: Neo4j properties cannot contain
maps, so structured provenance/evidence failed with a property type error. The
existing synchronizer was repaired to serialize structured values as
deterministic JSON strings. The same 28 documents then synchronized successfully.

## Graph results after first synchronization

| Node label | Count |
|---|---:|
| ThreatReport | 28 |
| Source | 7 |
| ThreatActor | 8 |
| Campaign | 66 |
| Malware | 4 |
| Tool | 5 |
| Vulnerability | 35 |
| Indicator | 1,147 |
| ATTACKTechnique | 0 |
| Sector | 7 |

| Relationship type | Count |
|---|---:|
| MENTIONS | 1,508 |
| REPORTED_BY | 28 |

All 1,508 entity links contain evidence, confidence, origin, status, and
extraction timestamp. All 28 report nodes contain source provenance. The 28
`REPORTED_BY` relationships contain source-confirmed origin and observation
timestamps. No `PART_OF_CAMPAIGN` or fabricated cross-report relationship was
created; campaign-labelled nodes are only evidence-backed extracted entities.

Synchronization results: 28 succeeded, 0 failed. PostgreSQL contains 28
`GraphSyncState` rows with status `synced`.

## Idempotency

The same 28 documents were synchronized a second time:

- 28 succeeded, 0 failed.
- Every sync state had attempt count `2`.
- Node counts were unchanged.
- Relationship counts were unchanged.
- All report provenance values were unchanged.
- All entity-link evidence and confidence values were unchanged.

## Knowledge-graph similarity

The existing `knowledge_graph_relationship_similarity` implementation was run
without changing the six-feature schema. Inputs were derived from actual
Neo4j `ThreatReport-[:MENTIONS]->entity` paths using canonical
`(entity-label, relationship-type, entity-stable-id)` tuples.

| Case | Reports | Score | Available | Result |
|---|---|---:|---|---|
| Shared evidence-supported graph path | `ThreatReport:770a5d7d-7c48-417a-b351-d89fe1c49ea5` and `ThreatReport:7e3d2341-71fc-4167-bc52-694717948978` | 0.1348314606741573 | true | 12 shared canonical paths |
| Shared entities, no campaign association | Same pair; no `PART_OF_CAMPAIGN` exists | 0.1348314606741573 | true | Shared entity paths only |
| No graph connection | `ThreatReport:12f46234-c0d8-4b74-9a12-9917ad2b436f` and `ThreatReport:ff2f836a-32fa-4952-93c3-209099449728` | 0.0 | true | Empty intersection, both sets observed |
| Incomplete graph coverage | `ThreatReport:12e6978e-397f-4077-931d-3fc2caf640e8` and missing lookup | 0.5 | false | Existing neutral missing-data policy |

## Repeat synchronization

To synchronize another existing document through the API:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/graph/sync/documents/<document-uuid>
```

The UUID must be an existing `CTIDocument.id` whose source, normalized content,
and extracted associations are already present in PostgreSQL. Do not pass a
dataset report ID in place of the PostgreSQL UUID. The service uses stable IDs,
`MERGE`, retry handling, and PostgreSQL `graph_sync_states`.

Commands executed for this controlled run:

```powershell
docker compose --env-file .env -f infrastructure\docker-compose.yml up -d neo4j postgres
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m pip check
```

The sample load and the two synchronization passes were executed as one-off
Python invocations from `backend` that imported
`create_and_run_job`/`execute_ingestion_job` and `GraphSynchronizer` from the
existing application modules. No persistent loader or alternate graph writer
was added. The endpoint above is the supported repeatable API operation.

## Remaining limitations

- The controlled sample intentionally did not ingest all 12,095 reports.
- The sample has no persisted ATT&CK technique mappings, so the ATT&CK node
  count is zero.
- No direct campaign association was present; shared campaign entity mentions
  were not promoted to campaign membership.
- The similarity adapter currently consumes graph-derived relationship
  representations supplied by its caller; it does not itself fetch Neo4j.
- No labels, silver data, training dataset, or model were changed.
