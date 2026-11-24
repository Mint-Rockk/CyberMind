# Correlation Feature Quality Report

## Audit status

This document includes the historical v2 audit and the completed v3
recomputation. The v3 statistics are recorded in the final section after the
historical baseline.

The opening tables below are the historical v2 audit, captured before graph
coverage expansion. The completed v3 audit and recomputation are recorded in
the final section.

The original silver file remains unchanged. Its SHA-256 is
`bcec4a6d5924d666cfe73a5e6149bf3120a73aeaa7cf400f9a192e478d0a5599`.

## Scope

Audited 16,785 eligible silver-labelled pairs without changing the `correlation-features-v1` six-feature contract. The original values are compared with the v2 recomputation.

A neutral value of `0.5` is counted separately from missingness. Missingness is derived from the actual report representation and production feature semantics; it is not inferred solely from a score that could be a valid similarity.

## Original feature statistics

| Feature | Missing % | Zero % | Neutral % | Mean | Std dev | Min | Max |
|---|---:|---:|---:|---:|---:|---:|---:|
| `temporal_similarity` | 5.6002 | 93.7563 | 5.6002 | 0.03443551 | 0.13874115 | 0.0 | 1.0 |
| `entity_relationship_similarity` | 0.0000 | 0.0000 | 0.2383 | 0.05737997 | 0.07281335 | 0.0018656716417910447 | 1.0 |
| `behavioural_similarity` | 100.0000 | 0.0000 | 100.0000 | 0.5 | 0.0 | 0.5 | 0.5 |
| `attack_technique_similarity` | 99.8213 | 0.0357 | 99.8213 | 0.49931513 | 0.01726569 | 0.0 | 0.8125 |
| `semantic_similarity` | 0.0000 | 0.0000 | 100.0000 | 0.5 | 0.0 | 0.5 | 0.5 |
| `knowledge_graph_similarity` | 100.0000 | 0.0000 | 100.0000 | 0.5 | 0.0 | 0.5 | 0.5 |

## Updated feature statistics

| Feature | Missing % | Zero % | Neutral % | Mean | Std dev | Min | Max |
|---|---:|---:|---:|---:|---:|---:|---:|
| `temporal_similarity` | 5.6002 | 93.7563 | 5.6002 | 0.03443551 | 0.13874115 | 0.0 | 1.0 |
| `entity_relationship_similarity` | 0.0000 | 0.0000 | 0.2383 | 0.05737997 | 0.07281335 | 0.0018656716417910447 | 1.0 |
| `behavioural_similarity` | 100.0000 | 0.0000 | 100.0000 | 0.5 | 0.0 | 0.5 | 0.5 |
| `attack_technique_similarity` | 99.8213 | 0.0357 | 99.8213 | 0.49931513 | 0.01726569 | 0.0 | 0.8125 |
| `semantic_similarity` | 0.0000 | 0.0000 | 0.0000 | 0.74281606 | 0.0545401 | 0.4978597314328764 | 1.0 |
| `knowledge_graph_similarity` | 100.0000 | 0.0000 | 100.0000 | 0.5 | 0.0 | 0.5 | 0.5 |

## Findings

- Temporal and entity features use report dates and extracted entity sets. Their neutral values can be genuine similarity results; missingness is reported separately.
- The historical v2 behavioural feature was unavailable; v3 uses the
  deterministic source-grounded behavioural extractor described below.
- ATT&CK similarity is available only when both reports contain explicit ATT&CK references; absent references remain missing under the production policy.
- Semantic similarity was recomputed from normalized report text using the configured `sentence-transformers/all-MiniLM-L6-v2` model, version `all-MiniLM-L6-v2`, and 384-dimensional vectors. Embeddings are stored in `v2/report_embeddings.jsonl` and validated for finite values and dimension.
- The existing v2 feature artifact was generated before bulk graph
  synchronization, so its graph feature remains explicitly missing/neutral.
  The v3 graph feature uses the completed 12,095-report Neo4j projection.
- Qdrant was unavailable at generation time. The local embedding artifact is reproducible, but production Qdrant indexing still requires the service.

## Verified current dependency state

- Neo4j Community `5.26.5`: reachable and authenticated through the backend
  runtime; `RETURN 1 AS ok` succeeds. Final graph counts are 12,095
  `ThreatReport` nodes, 83,288 `MENTIONS`, and 12,095 `REPORTED_BY`
  relationships.
- Qdrant: unreachable at `http://127.0.0.1:6333`. This does not block local
  embedding generation or pairwise cosine similarity.
- Embeddings: 12,095 unique vectors, all finite, all dimension 384, using
  `sentence-transformers/all-MiniLM-L6-v2` with
  `whitespace-normalized-v1` preprocessing.

## Missingness interpretation

| Condition | Interpretation |
|---|---|
| `available=false`, score `0.5` | Missing required evidence; neutral materialization only |
| score `0.0` with `available=true` | Genuine dissimilarity |
| score in `(0,1)` with `available=true` | Computed similarity |
| score `0.5` with `available=true` | Genuine neutral similarity, where supported |

Behavioural and graph values are currently missing for the complete eligible
dataset, not genuine zero similarity. ATT&CK values are computable only for
pairs with explicit technique evidence. The semantic values in the existing v2
artifact are computed and finite; the original silver semantic column was
neutral because it predates the local embedding run.

## Group distributions

Full campaign and source distributions are in `v2/feature_quality_metadata.json` under `group_distributions`; the JSON retains the top 300 campaign-feature and source-feature groups by pair count. This avoids hiding source or campaign concentration while keeping the report readable.

## Reproducibility

Run `backend\\.venv\\Scripts\\python.exe -m training.correlation.feature_quality --processed-dir backend\\data\\correlation\\processed --output-dir backend\\data\\correlation\\processed\\v2`.

## Final v3 recomputation

The graph expansion and behavioural repair completed before the isolated v3
recomputation. The original silver labels, pair IDs, and label evidence were
preserved byte-for-byte in the v3 copies; the original silver dataset was not
overwritten.

| Feature | Missing % | Zero % | Neutral % | Mean | Std dev | Min | Max |
|---|---:|---:|---:|---:|---:|---:|---:|
| `temporal_similarity` | 5.6002 | 93.7563 | 5.6002 | 0.03443551 | 0.13874115 | 0.0 | 1.0 |
| `entity_relationship_similarity` | 0.0000 | 0.0000 | 0.2383 | 0.05737997 | 0.07281335 | 0.00186567 | 1.0 |
| `behavioural_similarity` | 24.7125 | 26.1865 | 28.7161 | 0.26738181 | 0.21637964 | 0.0 | 1.0 |
| `attack_technique_similarity` | 99.8213 | 0.0357 | 99.8213 | 0.49931513 | 0.01726569 | 0.0 | 0.8125 |
| `semantic_similarity` | 0.0000 | 0.0000 | 0.0000 | 0.74281606 | 0.05454010 | 0.49785973 | 1.0 |
| `knowledge_graph_similarity` | 0.0000 | 0.0000 | 0.2443 | 0.07036303 | 0.07933576 | 0.00186567 | 1.0 |

The v3 artifact is
`backend/data/correlation/processed/v3/feature_generation_metadata.json`.
It records `correlation-features-v1`, 16,785 pairs, 2,266 positive labels,
14,519 negative labels, 12,095 graph-covered reports, the 384-dimensional
`all-MiniLM-L6-v2` embedding configuration, and the deterministic behaviour
extractor version. A graph score of zero is a genuine observed absence of a
shared graph relationship; unavailable graph lookup is not present in v3.
