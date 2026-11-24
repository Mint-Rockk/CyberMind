# CyberMind Deployment Guide

## Prerequisites

Install Docker Desktop, Python 3.13+, Node.js 22+, npm, and Git through the
approved system software channel. Verify:

```powershell
python --version
node --version
npm --version
git --version
docker version
docker compose version
docker info
```

## Local setup

```powershell
Set-Location E:\genAI
Copy-Item .env.example .env
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Set-Location ..\frontend
npm ci
Set-Location ..
docker compose -f infrastructure\docker-compose.yml up -d
docker compose -f infrastructure\docker-compose.yml ps
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe run_server.py
```

Verify the graph separately:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/graph/status
```

The graph status must be `connected`; `unreachable`,
`authentication_failure`, and `invalid_configuration` are reported
explicitly. See
[backend/training/correlation/NEO4J_SETUP.md](../backend/training/correlation/NEO4J_SETUP.md).

In a second terminal:

```powershell
Set-Location E:\genAI\frontend
npm run dev
```

Production must replace example credentials with secret-manager values, bind
services to a private network, add TLS/reverse-proxy controls, replace interim
identity, and enforce SSRF/egress policy. Live service startup/restart was not
verified because the Docker daemon was unavailable.