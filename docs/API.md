# CyberMind API Guide

The versioned API is served under `/api/v1`. FastAPI publishes generated OpenAPI
at `/docs` and `/openapi.json` while the service is running.

## Resource groups

| Group | Purpose |
|---|---|
| `/sources`, `/ingestion` | Configure lawful public sources and run collection jobs |
| `/documents`, `/entities`, `/attack` | Inspect normalized CTI and derived evidence |
| `/correlations`, `/campaigns` | Store and investigate cross-source relationships |
| `/graph`, `/vector`, `/rag` | Query projections and retrieve evidence |
| `/investigations`, `/assistant` | Run grounded investigations and conversations |
| `/reports` | Generate, list, inspect, and download reports |
| `/reviews`, `/audit` | Submit analyst decisions and inspect admin audit history |
| `/model`, `/dashboard`, `/health` | Inspect predictor status, counts, and service health |

Graph routes expose predefined parameterized operations only; arbitrary Cypher,
SQL, or shell execution is not accepted. CTI content is untrusted data and must
not be treated as instructions.

## Authentication status

Production API access requires a signed bearer token derived from the analyst
identity and `AUTH_SECRET`. The legacy `X-Analyst-Id` header remains only for
development compatibility and must not be used as a production credential.
Object-level ownership/tenant authorization remains a deployment hardening
requirement for shared environments.