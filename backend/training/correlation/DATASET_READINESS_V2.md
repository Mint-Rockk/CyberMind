# Dataset Readiness V2

## Decision

**B. NOT READY — MORE DATA OR FEATURE WORK REQUIRED.**

This decision is based on verified runtime and file evidence. No model was
trained and no original dataset or silver label was changed.

## Baseline inventory

| Artifact | Verified result |
|---|---:|
| Unique normalized reports | 12,095 |
| Parsed report files | 15,735 |
| Reports with usable dates | 11,910 |
| Reports with extracted entities | 8,427 |
| Reports with explicit ATT&CK references | 81 |
| Candidate pairs analysed | 797,236 |
| Eligible silver pairs | 16,785 |
| Positive / negative silver pairs | 2,266 / 14,519 |
| Silver schema | `correlation-features-v1` |
| Original silver SHA-256 | `bcec4a6d5924d666cfe73a5e6149bf3120a73aeaa7cf400f9a192e478d0a5599` |

The previously reported weak-supervision counts were re-read from
`backend/data/correlation/weak_supervision/labelling_statistics.json` and
match the reported run: 2,531 provisional positives, 18,463 provisional
negatives, 776,242 uncertain, 19,595 high-confidence outcomes, 27 conflicts,
2,810 incomplete high-confidence outcomes, 145 campaign references, and
9 sources. The silver file contains only the 16,785 eligible rows.

## Feature completeness

The existing v2 artifact contains 16,785 rows under the unchanged six-feature
schema. Its verified distributions are recorded in
`v2/missingness_statistics.json` and summarized in
`FEATURE_QUALITY_REPORT.md`. Behavioural similarity is missing for 100% of
pairs, ATT&CK similarity is missing for 99.8213%, and knowledge-graph
similarity is missing for 100%. Semantic similarity is available for all
16,785 pairs in v2.

Missing values remain neutral `0.5` with `available=false`; they are not
genuine zero similarities. The canonical feature order and preprocessing were
not changed.

## Dependency and graph coverage

- Neo4j Community `5.26.5` is running and authenticated through the backend
  configuration. A basic Cypher query succeeds.
- Neo4j currently contains 28 `ThreatReport` nodes, 66 campaign entity nodes,
  8 threat actors, 4 malware, 5 tools, 35 vulnerabilities, 1,147 indicators,
  7 sectors, and no ATT&CK technique nodes. It contains 1,508 `MENTIONS` and
  28 `REPORTED_BY` relationships.
- The graph therefore covers 28 of 12,095 reports. Full graph-dependent
  recomputation is blocked. No unsupported edges or fabricated relationships
  were added.
- Qdrant is unreachable at `127.0.0.1:6333`; this is separate from the
  successful local embedding audit.

## Embeddings

The existing local cache contains 12,095 unique finite 384-dimensional
vectors from `sentence-transformers/all-MiniLM-L6-v2`, using
`whitespace-normalized-v1`. Local pairwise cosine computation does not require
Qdrant. The cache was reused for this audit; no model training or synthetic
embedding generation occurred.

## Labels, diversity, and validation limits

The labels are deterministic weak-supervision silver labels, not ground truth.
The class ratio is approximately 1:6.4 and the source/campaign distributions
remain subject to source concentration and report-pair leakage. Future
training should use class weighting and campaign/incident-grouped,
source-aware splits.

No independent campaign-level ground truth was found in the inspected
artifacts. A 200-row review template with blank independent-label and
reviewer-rationale fields is available at
`backend/data/correlation/processed/v2/independent_validation_sample.csv`.

## Remaining blockers

1. Synchronize the remaining eligible reports through the existing pipeline
   before recomputing the graph feature.
2. Provide normalized behavioural representations for the eligible reports.
3. Add independent human or external campaign-level validation.
4. Start Qdrant only when vector-storage/retrieval validation is required.

## Reproducibility

Run these commands from `E:\genAI`:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_correlation_features.py tests\test_neo4j_integration.py -q
Set-Location ..
docker compose -f infrastructure\docker-compose.yml ps
```

The Neo4j integration test is opt-in and requires
`CYBERMIND_NEO4J_INTEGRATION=1`. Do not run a bulk graph synchronization or
overwrite `processed\silver_correlation_pairs.csv` until graph coverage and
missingness evidence are complete.
