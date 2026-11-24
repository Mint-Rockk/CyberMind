# Dataset Readiness V3

## Decision

**B. NOT READY — MORE DATA OR FEATURE WORK REQUIRED.**

The six-feature v3 artifact is complete and schema-compatible, but independent
campaign-level validation is unavailable and substantial ATT&CK and behavioural
missingness remains. This supports audit and clearly labelled silver-label
experiments only; it does not support final supervised training or
ground-truth performance claims.

## Dataset and preservation checks

- Dataset: `correlation-dataset-v3`
- Schema: `correlation-features-v1`
- Eligible pairs: 16,785
- Labels: 2,266 positive and 14,519 negative
- Pair IDs and label values: identical to v2
- Label evidence: copied without modification
- Duplicate/reverse-duplicate pairs: 0
- Invalid or out-of-range feature values: 0
- Original silver dataset: not overwritten; prior SHA-256 remains
  `bcec4a6d5924d666cfe73a5e6149bf3120a73aeaa7cf400f9a192e478d0a5599`

## Feature completeness and distributions

| Feature | Missing % | Zero % | Neutral % | Mean | Std dev | Range |
|---|---:|---:|---:|---:|---:|---:|
| temporal | 5.6002 | 93.7563 | 5.6002 | 0.03443551 | 0.13874115 | 0–1 |
| entity relationship | 0.0000 | 0.0000 | 0.2383 | 0.05737997 | 0.07281335 | 0.00186567–1 |
| behavioural | 24.7125 | 26.1865 | 28.7161 | 0.26738181 | 0.21637964 | 0–1 |
| ATT&CK technique | 99.8213 | 0.0357 | 99.8213 | 0.49931513 | 0.01726569 | 0–0.8125 |
| semantic | 0.0000 | 0.0000 | 0.0000 | 0.74281606 | 0.05454010 | 0.49785973–1 |
| knowledge graph | 0.0000 | 0.0000 | 0.2443 | 0.07036303 | 0.07933576 | 0.00186567–1 |

Behavioural positive/negative means are 0.34550298 and 0.25518933;
knowledge-graph positive/negative means are 0.11940937 and 0.06270830.
Missing values remain neutral `0.5` with unavailable evidence, never genuine
zeroes. Genuine zeroes are retained only when the production calculation was
available and found no overlap.

## Graph and embeddings

Neo4j 5.26.5 is authenticated and queryable. Coverage increased from 28 to
12,095 `ThreatReport` nodes (100%), with provenance on all reports, 8,317
reports linked to entities, 83,288 `MENTIONS`, and 12,095 `REPORTED_BY`
relationships. There are 1,039 campaign nodes but no direct report-to-campaign
relationships were inferred. Qdrant remains unreachable; this does not block
the local pairwise cosine computation. All 12,095 report embeddings are finite
384-dimensional `sentence-transformers/all-MiniLM-L6-v2` vectors.

## Diversity and validation limits

The silver run contains 145 campaign references across 9 sources, but the
labels are weakly supervised and campaign/source concentration remains a
leakage risk. Future evaluation should use campaign/incident-grouped splits
and class weighting rather than duplicating pairs. No genuinely independent
campaign annotations or completed reviewer labels were found. The existing
independent-review template remains separate from silver labels, with blank
independent-label and reviewer-rationale fields.

## Reproducibility

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m training.correlation.sync_normalized_reports --offset 0 --limit 100 --dry-run
.\.venv\Scripts\python.exe -m training.correlation.recompute_v3
.\.venv\Scripts\python.exe -m pytest tests\test_normalization.py tests\test_correlation_features.py tests\test_graph.py -q
```

The v3 metadata, embeddings, labels, and feature rows are under
`backend/data/correlation/processed/v3/`.
