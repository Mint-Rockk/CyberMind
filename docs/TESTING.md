# Testing Guide

## Backend

```powershell
Set-Location E:\genAI\backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app run_server.py
```

The suite covers unit, SQLite-backed database/API, normalization, extraction,
classification, ATT&CK, correlation, campaigns, graph adapters, vector/RAG,
GenAI, reporting, review, and permissions. Live PostgreSQL, Neo4j, Qdrant, and
provider tests require those services and credentials.

## Frontend and dependency audits

```powershell
Set-Location E:\genAI\frontend
npm ci
npm run build
npm audit --omit=dev --audit-level=moderate
Set-Location ..\backend
.\.venv\Scripts\python.exe -m pip_audit -r requirements.txt
.\.venv\Scripts\python.exe -m pip_audit -r requirements-dev.txt
```

There is currently no separate frontend unit-test runner or browser test suite;
browser smoke checks are a hardening follow-up.