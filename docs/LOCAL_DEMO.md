# Local fictional CTI demonstration

CyberMind includes five fictional publications and 40 synthetic reports (eight per
publication). The articles, actors, campaigns, organisations, product names, and
indicators are demonstration data only. Reserved `.example` hostnames and
documentation-only IP ranges are used; no live exploit steps or executable samples are
provided.

## Start the services

The existing Compose stack provides PostgreSQL, Neo4j Community Edition, and Qdrant.
Keep an existing `.env`; do not overwrite it. If one does not exist, create it from the
placeholder file and replace the local passwords before starting Compose:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose --env-file .env -f infrastructure\docker-compose.yml up -d
docker compose --env-file .env -f infrastructure\docker-compose.yml ps
```

In a backend terminal:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.demo.seed
.\.venv\Scripts\python.exe run_server.py
```

In a frontend terminal:

```powershell
Set-Location frontend
npm run dev
```

The seed command is safe to repeat. It disables active non-demo source records without
deleting them, upserts the five local advisory sources, and does not alter reports,
model artifacts, datasets, or graph/vector volumes. Demo sources are scheduled for
collection every 60 minutes and can also be collected immediately from the Sources
page.

## Fictional publication sites and feeds

Backend routes host all five sites at `http://127.0.0.1:8000`; the same site routes work
with `localhost`.

| Publication | Website | Feed |
|---|---|---|
| CyberWatch Intelligence | <http://127.0.0.1:8000/demo-sites/cyberwatch/> | <http://127.0.0.1:8000/demo-sites/cyberwatch/feed.json> |
| MalwareScope | <http://127.0.0.1:8000/demo-sites/malwarescope/> | <http://127.0.0.1:8000/demo-sites/malwarescope/feed.json> |
| ThreatActor Research | <http://127.0.0.1:8000/demo-sites/threatactor/> | <http://127.0.0.1:8000/demo-sites/threatactor/feed.json> |
| VulnTracker | <http://127.0.0.1:8000/demo-sites/vulntracker/> | <http://127.0.0.1:8000/demo-sites/vulntracker/feed.json> |
| APT Research Centre | <http://127.0.0.1:8000/demo-sites/aptresearch/> | <http://127.0.0.1:8000/demo-sites/aptresearch/feed.json> |

The site directory is <http://127.0.0.1:8000/demo-sites/>. Each publication has a
branded report listing, search/category filters, stable report IDs, article detail
pages, and its own JSON feed.

## Collect and inspect

1. Open <http://localhost:5173/sources>.
2. Select **Collect now** for each active fictional source.
3. Use **Intelligence**, **ATT&CK**, **Correlations**, **Campaigns**, **Graph**, and
   **Semantic Search** to inspect the persisted results.
4. Open **Assistant** and ask a question grounded in the collected reports. With
   `GENAI_PROVIDER=disabled`, CyberMind returns cited retrieved excerpts and explicitly
   labels them as extractive rather than generated synthesis.

Collection fetches and parses each actual JSON feed. Repeated collection preserves the
existing `(source, external article ID)` idempotency key and does not create another
document for an already collected article. Source collection status and the number of
non-duplicate reports are shown on the Sources page.

The demo pipeline reuses existing entity extraction, Neo4j synchronization, Qdrant
chunking/indexing, correlation feature calculation, and the saved evidence-aware
`f1-improvement-v3` predictor. It uses the artifact's saved 12-feature order and
selected threshold; it does not retrain or modify artifacts. Explicit ATT&CK IDs are
mapped against an offline subset used by this corpus. Campaign names from feed
metadata are stored as `synthetic_demo_ground_truth`, are not treated as model output,
and are excluded from model candidate/entity evidence and knowledge-graph correlation
features.

On the Campaigns page, **Run naming** groups existing saved related correlations using
demonstration defaults of probability `0.35` and supporting non-temporal similarity
`0.10`. These thresholds do not recalculate or alter model predictions. Results remain
provisional and require analyst review. The page lets an analyst raise either threshold.
Running naming sends eligible report excerpts and saved evidence to the configured GenAI
provider; synthetic demo labels are withheld. Candidate names are marked AI-generated
only after structured output passes evidence validation. With
`GENAI_PROVIDER=disabled` or an unavailable provider, a clearly identified deterministic
fallback is saved instead. To enable provider-backed names, configure the existing
`GENAI_PROVIDER`, `GENAI_API_KEY`, and `GENAI_MODEL` settings before starting the backend.
For Gemini demonstrations, `gemini-3.5-flash-lite` with `GENAI_TIMEOUT=60` is configured
for responsive naming; the Campaigns page allows up to four minutes when several groups
are processed.
