# CyberMind Dependency and Prerequisite Inventory

**Inspection date:** 2026-11-17  
**Repository:** `E:\genAI`  
**Current state:** Foundational backend/frontend source, manifests, lockfiles, and Docker Compose definitions are present. CTI and intelligence dependencies remain intentionally uninstalled until their implementation phases.

## 1. Repository inspection

| Item | Result |
|---|---|
| Root contents | Foundation source, manifests, documentation, and infrastructure definitions |
| Git repository | Not present |
| Python manifests | `backend\pyproject.toml`, `backend\requirements.txt`, `backend\requirements-dev.txt`, `backend\requirements.lock.txt` |
| Node manifests | `frontend\package.json`, `frontend\package-lock.json` |
| Docker/deployment files | `infrastructure\docker-compose.yml` |
| Existing application source | Foundational FastAPI and React/Vite shell |
| Editable package metadata | Existing global `cybermind-backend 0.1.0` entry remains outside the project environment and was not used |

The editable package metadata reports these Python requirements: `alembic`, `apscheduler`, `fastapi`, `psycopg`, `pydantic-settings`, `sqlalchemy`, and `uvicorn`. This is environment evidence only, not a project manifest.

## 2. Installed prerequisite tools

| Prerequisite | Installed version/status | Evidence and notes |
|---|---|---|
| Python | 3.13.7, 64-bit | `C:\Users\Abhishek\AppData\Local\Programs\Python\Python313\python.exe` |
| pip | 25.2 | Installed with the Python 3.13 runtime |
| Node.js | v22.17.0 | Installed |
| npm | 10.9.2 | Installed; global package directory is currently missing |
| Git | 2.51.0.windows.1 | Installed; `E:\genAI` is not a Git repository |
| Docker CLI | 29.4.1 | Installed; context is `desktop-linux` |
| Docker Compose | v5.1.3 | Installed as Docker CLI plugin and standalone command |
| Docker daemon | UNAVAILABLE | Docker client could not connect to `dockerDesktopLinuxEngine`; Docker Desktop/daemon must be running before container startup validation |
| Poetry | Not found | Optional; do not install unless selected as the project package manager |
| uv | Not found | Optional; do not install unless selected as the project package manager |
| pnpm | Not found | Optional; npm is already available |
| yarn | Not found | Optional; npm is already available |

## 3. Relevant Python packages already visible

The project-local backend environment was created at `backend\.venv` and verified with Python imports. Its locked foundational versions include FastAPI 0.163.1, Pydantic 2.14.3, Pydantic Settings 2.16.3, SQLAlchemy 2.1.8, greenlet 3.5.6 (required by SQLAlchemy asyncio), Alembic 1.20.1, psycopg 3.3.9, Uvicorn 0.54.0, HTTPX 0.28.1, python-dotenv 1.2.4, and pytest 8.4.2. The complete lock is in `backend\requirements.lock.txt`.

The global Python environment was not modified. It reported an invalid `~orch` distribution, which is unrelated to the project-local environment.

Collection dependencies are now installed in `backend\.venv` and locked in `backend\requirements.lock.txt`: `feedparser` for RSS, `stix2` for STIX validation/serialization, `taxii2-client` for TAXII compatibility, `APScheduler` for scheduled jobs, and `tenacity` for bounded retries. `aiosqlite` is a development-only dependency used by isolated API tests; production collection remains PostgreSQL-backed.

Document normalization dependencies are also installed in the project environment: `beautifulsoup4` for HTML cleaning, `python-dateutil` for tolerant timestamp parsing, and `rapidfuzz` for near-duplicate comparison. These are pinned by the requirements ranges and captured in `backend\requirements.lock.txt`.

Correlation predictor integration now uses `scikit-learn` and its `joblib` dependency for
trusted external artifact loading and scikit-learn-compatible `predict_proba` contracts.
No trained model artifact was installed or created. XGBoost remains optional and is not
installed because no XGBoost artifact has been supplied.

Semantic indexing uses `qdrant-client 1.20.0`, `sentence-transformers 5.7.0`,
`torch 2.15.0`, and their locked transitive dependencies. The pretrained
`sentence-transformers/all-MiniLM-L6-v2` model was downloaded to the local Hugging Face
cache and verified at 384 dimensions. No fine-tuning or custom embedding training was
performed.

Report generation uses `reportlab 4.5.1` (with `Pillow 13.0.0`) in the project
environment for deterministic PDF rendering. No external document service is
required.

## 4. Planned runtime/service dependencies

These are required by the target architecture:

| Dependency | Purpose | Planned validation |
|---|---|---|
| PostgreSQL | Authoritative relational store and migrations | Version pin in project deployment files; migration integration tests; currently unavailable |
| Neo4j | CTI entity/relationship knowledge graph | Version pin, graph projection tests, and live connectivity check; Python driver `neo4j 5.28.8` is installed in `backend\.venv` |
| Qdrant | Versioned vector retrieval | Version pin, collection/re-index tests, and live service check; `qdrant-client 1.20.0` is installed in `backend\.venv` |
| Object storage or controlled raw volume | Immutable raw payloads and report artifacts | Deployment decision required |
| Queue/cache (Redis or equivalent) | Optional scheduling, rate limiting, and worker state | Select only after throughput design |
| Embedding provider/runtime | Semantic feature and retrieval generation | Local pretrained Sentence Transformer installed and verified; model/configuration documented in `SEMANTIC_INDEXING.md` |
| GenAI provider/runtime | Evidence-grounded investigation and assistant | Provider, retention, and policy decision required; intentionally not installed |

Correlation feature engineering currently requires no additional package: date-window
arithmetic, set similarity, cosine similarity, schema validation, and graph-relationship
comparison use the Python standard library. The Neo4j driver and local pretrained
embedding runtime are installed for the graph projection and semantic indexing adapters.

Backend and frontend development servers were started and verified. Database containers were not started because the Docker daemon was unavailable; Compose syntax was validated with `docker compose config`.

## 5. Exact installation commands for later stages

The following commands are recorded for later use only. They were **not** executed during this planning-only task.

### Python project environment (completed for foundation and graph integration)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install "neo4j>=5.25,<6"
```

If the project selects `uv` instead of venv/pip, document that decision first and use a committed lockfile; do not mix managers casually.

### Node frontend (completed for foundation)

```powershell
Set-Location frontend
npm ci
```

`npm ci` requires a committed `package-lock.json`; use `npm install` only when creating or intentionally updating the manifest and lockfile.

### Docker Desktop

Install Docker Desktop through the approved organizational/software channel, then start Docker Desktop and verify:

```powershell
docker version
docker compose version
docker info
```

Do not install Docker again while the existing client is present.

### Local service stack

After version-pinned deployment files are created:

```powershell
docker compose -f infra\docker-compose.yml up -d postgres neo4j qdrant
docker compose -f infra\docker-compose.yml ps
```

The service definitions are present in `infrastructure\docker-compose.yml`; container startup remains blocked until Docker Desktop is running. Model creation, relationships, uniqueness constraints, and correlation feature persistence were verified against an in-memory SQLite test database. A direct PostgreSQL connection attempt to `localhost:5432` timed out.

### Database migration

After PostgreSQL is running and `.env` points to the configured database:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

The initial migration is `20261116_0001_initial_schema.py`; graph synchronization state is added by
`20261116_0008_graph_sync_state.py`. No production data is created by migrations.

## 6. Security and deployment verification

- `npm audit --omit=dev --audit-level=moderate`: **PASS**, 0 production vulnerabilities.
- `pip-audit -r requirements.txt`: **PASS**, no known vulnerabilities in runtime requirements.
- `pip-audit -r requirements-dev.txt`: the declared `pytest>=9.0.3` range is selected to avoid the reported `pytest 8.4.2` advisory; rerun after lock regeneration.
- `docker compose -f infrastructure\docker-compose.yml config --quiet`: **PASS**.
- Docker daemon and ports 5432, 7474, 7687, 6333, and 6334: **UNAVAILABLE** in the inspected environment.
- PostgreSQL migrations: offline SQL generation through `20261116_0012` previously passed; live upgrade is blocked by the unavailable daemon.

The trained correlation model has **not** been supplied or integrated. The baseline predictor is the active verified predictor, and the trained-model adapter is ready to validate a future compatible artifact.

## 7. Dependency governance

- Choose one Python dependency manager and commit a lock/constraints strategy.
- Commit the frontend lockfile and use `npm ci` in CI.
- Pin infrastructure service major/minor versions after compatibility testing.
- Do not add a package merely because it exists globally.
- Run vulnerability/license checks against committed manifests.
- Keep secrets in environment/secret-manager configuration, never in manifests or source.
- Re-run this inventory when scaffolding creates the actual manifests.
