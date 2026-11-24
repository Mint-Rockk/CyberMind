# CyberMind Database Schema

PostgreSQL is the authoritative system of record. Alembic migrations are in
`backend/alembic/versions`; the current migration head is `20261116_0012`.

Core tables include `users`, `cti_sources`, `ingestion_jobs`,
`raw_source_records`, `cti_documents`, `entities`,
`document_entity_associations`, `attack_techniques`,
`document_technique_mappings`, `correlation_records`, `correlation_jobs`,
`campaigns` and their history/associations, `graph_sync_states`,
`investigations`, assistant conversations/messages, generated reports,
`analyst_reviews`, and `audit_logs`.

Foreign keys, uniqueness constraints, indexes, timestamps, and JSON evidence
fields are defined in `backend/app/db/models.py`. Run migrations before using
data-backed API routes. Review and audit records are append-only from the
application perspective.