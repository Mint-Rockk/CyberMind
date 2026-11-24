# CyberMind Development Roadmap

This roadmap is intentionally implementation-oriented. Completed work is recorded in `PROJECT_CHECKLIST.md`; remaining phase work is not implied to be complete by the existence of an implementation scaffold.

## Phase 0 - Baseline and decisions

**Exit criteria**

- [PROJECT_CHECKLIST.md](./PROJECT_CHECKLIST.md), [ARCHITECTURE.md](./ARCHITECTURE.md), and [DEPENDENCIES.md](./DEPENDENCIES.md) are reviewed.
- Open decisions in the architecture document are resolved.
- Public-source legal, attribution, retention, and rate-limit policy is approved.
- Initial API, canonical CTI, provenance, confidence, and feature contracts are versioned.

## Phase 1 - Foundation

**Work**

- Scaffold backend, frontend, tests, documentation, and infrastructure directories.
- Add environment configuration, structured logging, health/readiness endpoints, error contracts, and CI.
- Establish PostgreSQL connectivity and Alembic migration workflow.
- Implement authentication/authorization foundations and audit event primitives.

**Exit criteria**

- Clean local setup from documented commands.
- Migration upgrade/downgrade checks pass.
- CI runs formatting, lint, type checks, and focused tests.

## Phase 2 - Collection and canonical CTI

**Work**

- Implement source connector interface and first lawful public connectors: RSS, NVD/CVE, MITRE ATT&CK, and selected advisories.
- Add raw payload retention, retrieval metadata, source policies, retry/rate limiting, and idempotency.
- Implement normalization, deterministic identity, deduplication, and provenance.
- Add entity extraction, classification, source reliability, and information confidence contracts.

**Exit criteria**

- Connector fixtures replay deterministically.
- Duplicate inputs converge without losing provenance.
- Every derived record links to source evidence and transformation versions.

## Phase 3 - ATT&CK, features, and correlation

**Work**

- Add versioned MITRE ATT&CK synchronization and evidence-backed mappings.
- Implement all six correlation dimensions: temporal, infrastructure, behavioral, contextual, semantic, and relational/entity-linkage.
- Define feature schema/version compatibility and missingness behavior.
- Implement the deterministic baseline predictor and evaluation harness.
- Implement a model adapter and registry contract for the user-supplied trained model; do not train a model in this project phase.

**Exit criteria**

- Dimension-level evidence is inspectable.
- Feature records are reproducible and schema-versioned.
- Baseline metrics and calibration are recorded on fixed evaluation fixtures.
- A contract test proves a compatible external model can be loaded without rewriting the pipeline.

## Phase 4 - Campaign discovery and search systems

**Work**

- Generate evidence-backed candidates and campaign hypotheses with thresholds and uncertainty.
- Add Neo4j projection and idempotent graph queries.
- Add Qdrant collections, embedding metadata, filters, and re-indexing.
- Add graph and semantic retrieval APIs.

**Exit criteria**

- Graph and vector projections can be rebuilt from canonical data.
- Retrieval results preserve source citations and version metadata.
- Candidate state transitions are authorized and audited.

## Phase 5 - RAG, assistant, reporting, and review

**Work**

- Assemble evidence-grounded RAG context with fact/inference/unknown separation.
- Add provider/model adapters, prompt-injection controls, cost/retention policies, and assistant conversations.
- Generate reproducible investigation reports with citations and redaction.
- Implement human review queues, corrections, feedback, approvals/rejections, and immutable audit events.

**Exit criteria**

- Responses and reports cite retrieved evidence.
- Unsupported claims are rejected or clearly marked as uncertain.
- Review actions are fully auditable and permission checked.

## Phase 6 - Dashboard and analyst UX

**Work**

- Build dashboard, source/feed management, search, entity/indicator detail, correlation/campaign investigation, graph, assistant, report, and review modules.
- Add stale-data, loading, error, confidence, citation, and accessibility states.
- Add typed client contract tests and end-to-end analyst workflows.

**Exit criteria**

- Core analyst journey works against seeded test data.
- UI authorization and failure states are tested.
- Accessibility and browser checks pass for critical workflows.

## Phase 7 - Evaluation, hardening, and deployment

**Work**

- Add security, dependency, migration, integration, contract, end-to-end, and performance tests.
- Resolve the security review gates: signed authentication, object-level authorization, SSRF/egress policy, secret isolation, rate limiting, and secure service credentials.
- Define extraction/classification/correlation/retrieval/report evaluation datasets and metrics.
- Add Docker-based local services, production deployment configuration, backups, restore, re-indexing, rollback, and disaster-recovery runbooks.
- Validate operational telemetry and alerting.

**Exit criteria**

- Release gates and quality thresholds are documented and reproducible.
- Deployment can be recreated from version-controlled configuration without secrets.
- Recovery procedures have been exercised.

## Model integration gate

The correlation pipeline must be stable before a trained model is integrated. The model integration gate requires:

- A published feature schema version.
- Adapter input/output contract tests.
- Model metadata including version, training data reference, feature schema, calibration, and approval state.
- Safe fallback to the baseline predictor when a registered model is unavailable or incompatible.
- No fabricated weights, training results, or performance claims.

## Checklist update protocol

Before starting a phase, set its relevant checklist rows to `IN PROGRESS`. Set a row to `COMPLETED` only when implementation evidence and tests are recorded. Use `BLOCKED` with a concrete decision, dependency, or environment failure when work cannot proceed.
