# CyberMind Architecture

**Baseline:** 2026-11-16  
**Current implementation state:** Foundation, CTI processing, correlation/campaign workflows, Neo4j graph projection/query boundary, Qdrant semantic indexing/retrieval, hybrid evidence retrieval, provider-independent GenAI investigation/assistant adapters, deterministic reporting, and analyst review are implemented. Production authentication, SSRF policy enforcement, live service validation, and deployment hardening remain open.

## 1. Product boundary

CyberMind is an external-source Cyber Threat Intelligence platform. It collects and analyzes lawful public CTI, including RSS feeds, security advisories, NVD/CVE data, MITRE ATT&CK, OSINT, and research reports.

Out of scope:

- Internal network-traffic IDS or packet inspection
- SIEM ingestion and correlation
- EDR or endpoint telemetry monitoring
- Unauthorized collection or exploitation of private systems

## 2. Architectural principles

1. **Evidence first:** retain the source record, retrieval metadata, transformation versions, and citations for every derived claim.
2. **Replaceable intelligence:** correlation, embeddings, LLM providers, and classifiers are adapters behind versioned contracts.
3. **Human accountable:** high-impact campaign and response conclusions require review states and auditable analyst actions.
4. **Idempotent pipelines:** retries must not duplicate source records, entities, graph edges, or vectors.
5. **Explicit uncertainty:** source reliability, claim confidence, model confidence, and LLM-generated inference remain separate.
6. **Public-source safety:** outbound fetching must be allowlisted/configured, rate-limited, bounded, and protected against SSRF and malicious content before production exposure.

## 3. Target system context

```text
Public CTI sources
  RSS | advisories | NVD/CVE | MITRE ATT&CK | OSINT | research reports
                              |
                              v
                    Collection and raw archive
                              |
                              v
              Normalize -> deduplicate -> provenance
                              |
              +---------------+----------------+
              v                                v
       Entity/classification              Feature builder
              |                                |
              v                                v
       PostgreSQL system of record    Baseline/model adapter
              |                                |
              +---------------+----------------+
                              v
               Campaign candidates and correlation
                       /                 \
                      v                   v
               Neo4j graph          Qdrant vectors
                      \                   /
                       v                 v
                         RAG and GenAI
                              |
                 Assistant, reports, review queue
                              |
                         Web dashboard
```

## 4. Proposed repository structure

```text
backend/
  app/
    api/                 # Versioned HTTP routes and schemas
    core/                # Settings, logging, security, lifecycle
    db/                  # SQLAlchemy models, repositories, migrations
    collectors/          # Source-specific public CTI connectors
    ingestion/           # Raw retrieval and job orchestration
    normalization/       # Canonical CTI transformation
    deduplication/       # Identity, similarity, and merge decisions
    extraction/          # Entity and observable extraction
    classification/      # Taxonomy and label assignment
    confidence/          # Reliability and information confidence
    attack/              # MITRE ATT&CK synchronization and mapping
    correlation/         # Six dimensions, features, predictors
    campaigns/           # Candidate generation and campaign lifecycle
    graph/               # Neo4j client, stable graph projection, and safe query services
    vector_store/        # Qdrant collections, chunking, and embedding adapter
    rag/                 # Hybrid retrieval and evidence assembly
    genai/               # Provider/model policy adapter
    assistant/           # Analyst assistant use cases
    reports/             # Reproducible report generation
    review/              # Human-in-the-loop workflows
    audit/               # Immutable audit events
  tests/
  alembic/
frontend/
  src/
    api/                 # Typed API client
    modules/
      dashboard/ sources/ search/ entities/ correlation/
      graph/ assistant/ reports/ review/ settings/
    shared/              # UI components, types, auth, errors
ml/
  features/              # Versioned feature schema
  adapters/              # User-supplied trained-model adapters
  registry/               # Model metadata and compatibility
evaluation/               # Datasets, metrics, and evaluation runners
infrastructure/           # Local services, deployment, observability
docs/                     # API and operational documentation
```

## 5. Data ownership

- **PostgreSQL:** source metadata, raw-record references, normalized CTI, entities, classifications, provenance, confidence, campaigns, review state, users, and audit events.
- **Object storage or controlled raw volume:** immutable raw payloads and report artifacts; the final choice requires a deployment decision.
- **Neo4j:** queryable entity and relationship projection for graph investigation. PostgreSQL remains the authoritative audit and lifecycle store; `graph_sync_states` records projection attempts and failures.
- **GenAI investigation:** provider-independent LLM adapter consumes only hybrid-RAG evidence. Retrieved CTI is untrusted data; structured outputs require evidence IDs and are persisted with provider metadata without changing correlation, campaign, or analyst-review state.
- **Human review and audit:** active analysts submit append-only decisions against bounded target types. Corrections use field allowlists, campaign decisions retain campaign history, and admin-only audit reads expose original/updated values, reasons, evidence, and actors. No external infrastructure action is automated.
- **Qdrant:** versioned embeddings and retrieval metadata. It is rebuildable from canonical source records; the collection contract is documented in [SEMANTIC_INDEXING.md](./SEMANTIC_INDEXING.md).
- **Redis or a managed queue (decision pending):** job scheduling, rate limiting, and short-lived task state if required by throughput.

## 6. Correlation contract

The correlation service will compute independently inspectable evidence for the six stable
model features defined in `MODEL_INTEGRATION.md`:

1. **Temporal:** overlapping activity windows, publication/retrieval timing, and sequence compatibility.
2. **Entity relationship:** shared normalized extracted entities.
3. **Behavioural:** shared behaviors, tactics, procedures, and observed actions in public reporting.
4. **MITRE ATT&CK technique:** shared ATT&CK technique and sub-technique identifiers.
5. **Semantic embedding:** normalized cosine similarity of compatible explicit embeddings.
6. **Knowledge-graph relationship:** shared canonical subject/predicate/object relationships.

Infrastructure and contextual signals may contribute to upstream representations, but they
are not silently added as model inputs.

The output contract should include candidate IDs, dimension evidence, feature-schema version, predictor/model identity, score, calibration metadata, citations, and uncertainty. The baseline predictor is deterministic and separately deployable. The trained Cross-Source Threat Correlation Model will be supplied by the user later through an adapter; CyberMind will not train or fabricate it.

## 7. Processing lifecycle

1. Schedule or trigger a source-specific collection job.
2. Fetch within configured source policy, store immutable raw payload and retrieval metadata.
3. Normalize into canonical records and assign a stable content identity.
4. Deduplicate while preserving all source/provenance links.
5. Extract entities/observables, classify content, and map supported MITRE ATT&CK references.
6. Calculate source reliability and claim information confidence.
7. Build the versioned feature record and run baseline or registered model adapter.
8. Create evidence-backed candidates and campaign hypotheses.
9. Project canonical relationships to Neo4j and searchable chunks to Qdrant.
10. Assemble cited retrieval context for analyst or future GenAI investigation.
11. Route consequential findings through review, record the decision, and generate reports.

Each stage must be idempotent, observable, retryable, and auditable.

Neo4j projections use stable IDs and `MERGE` for duplicate-safe writes. Relationship
properties retain evidence, observed timestamps, and `source_confirmed` versus
`system_inferred` origin. Graph reads are limited to predefined parameterized services;
arbitrary Cypher is never accepted from API clients.

Qdrant projections use deterministic chunk IDs, a configured pretrained Sentence
Transformer, explicit vector dimensions, and payload filters. Re-indexing deletes
the prior document points before upserting the current chunk set, so changed
documents do not leave stale vectors.

The RAG retrieval boundary combines Qdrant, PostgreSQL, and predefined Neo4j
queries. It returns evidence items and source references, never an unsupported
answer; unavailable stores and empty matches are explicit warnings.

## 8. API and frontend boundaries

The backend will expose versioned REST APIs with generated OpenAPI documentation. Major resource groups are sources, records, indicators, entities, mappings, correlations, campaigns, graph queries, investigations, assistant conversations, reports, reviews, and audit events.

The frontend will use a typed client and authorization-aware modules for dashboard, source/feed management, CTI search, entity/indicator detail, correlation and campaign investigation, graph exploration, assistant, reports, and human review. Loading, error, empty, stale-data, confidence, and citation states are first-class UI states.

## 9. Security and governance

Required controls include authenticated sessions, role-based authorization, input/schema validation, secret management, safe outbound HTTP, SSRF protections, content-size/time limits, dependency scanning, audit logging, prompt-injection-resistant retrieval, provider policy controls, redaction, and rate limiting. Public-source licenses, terms, attribution, retention, and deletion rules must be recorded per connector.

## 10. Security and deployment gates

The current implementation is not production-ready without the following gates:

- Add object-level ownership/tenant authorization and replace development-only identity compatibility with the deployment identity provider.
- Restrict source creation and ingestion to authorized administrators and validate DNS/IP destinations, redirects, headers, and secret selection.
- Remove default service credentials, bind local services to loopback or a private network, and use deployment-provided secrets.
- Add API rate limiting, structured security logging, and live PostgreSQL, Neo4j, and Qdrant health checks.

## 11. Open decisions before production deployment

- Backend/frontend repository packaging and frontend framework.
- PostgreSQL/object-storage/queue topology for local and production environments.
- Authentication provider and analyst roles.
- Initial public feed allowlist and legal/retention policy.
- Canonical entity taxonomy and confidence calibration policy.
- Embedding provider and GenAI provider.
- Model registry format and adapter runtime boundary.
