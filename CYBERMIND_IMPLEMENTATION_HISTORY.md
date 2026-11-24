# CyberMind Implementation History

## Scope

This document summarizes the completed CyberMind CTI correlation, knowledge-graph,
feature-quality, model-training, and application-integration work completed in this
development session.

CyberMind is an external-source Cyber Threat Intelligence (CTI) platform that
collects public reports, extracts entities and ATT&CK techniques, correlates reports,
maintains a knowledge graph, and supports analyst investigations with RAG and GenAI
components.

The original datasets, pair IDs, labels, six-feature schema, split assignments, and
previous experiment artifacts were preserved. New datasets and experiments were
written to versioned directories.

## 1. Neo4j setup and knowledge-graph integration

### Existing architecture inspected

- Existing Neo4j driver, client, graph service, schema, synchronization, and health
  paths were reused.
- The backend uses the Neo4j Python driver over Bolt.
- Neo4j Community Edition `5.26.5` was configured.
- The Neo4j Python driver version is `5.28.8`.
- The configured database is `neo4j`.
- Existing stable identifiers, `MERGE` writes, provenance, retries, and graph
  synchronization behavior were preserved.

### Connection and health behavior

The integration supports explicit health states for:

- Connected.
- Unreachable.
- Authentication failure.
- Invalid configuration.

The connection manager verifies that the process is reachable, authentication
succeeds, the configured database is available, and a basic Cypher query executes.
Sessions and drivers are closed through the existing lifecycle.

### Graph synchronization

A resumable, dry-run-capable graph synchronization workflow was added and verified.
It reuses the existing entity extraction and graph projection paths rather than
introducing a separate graph architecture.

Graph coverage increased from 28 reports to 12,095 reports.

The graph represents the entities and relationships supported by the existing
CyberMind schema, including:

- Threat actors.
- Campaigns.
- Malware.
- Tools.
- Vulnerabilities.
- Indicators.
- ATT&CK techniques.
- Target sectors.
- CTI reports and source documents where represented by the existing model.

Shared actors, malware, tools, or techniques are not treated as proof of campaign
membership.

## 2. Behavioural extraction and ingestion repairs

The deterministic behavioural extractor was expanded and versioned as
`deterministic_behaviour_lexicon_v2`.

The additional source-grounded patterns include:

- Downloads.
- User execution.
- Process injection.
- Startup persistence.
- Browser credential theft.
- Discovery.
- Remote services.
- File search.
- Staged data.
- Artifact removal.

Behaviour evidence retains availability, provenance, and confidence. Unavailable
evidence remains explicitly unavailable and is materialized according to the existing
neutral missing-value policy.

A PostgreSQL ingestion failure caused by NUL bytes was fixed in shared text
normalization.

## 3. Canonical correlation feature contract

The six canonical features remain unchanged:

1. `temporal_similarity`
2. `entity_relationship_similarity`
3. `behavioural_similarity`
4. `attack_technique_similarity`
5. `semantic_embedding_similarity`
6. `knowledge_graph_relationship_similarity`

The schema version remains:

```text
correlation-features-v1
```

The missing-data policy remains:

- A feature with unavailable evidence receives neutral score `0.5`.
- Evidence retains `available=false` and a missing reason.
- Missing evidence is never silently converted to zero or fabricated evidence.

The locally installed sentence-transformer model is:

```text
sentence-transformers/all-MiniLM-L6-v2
```

It produces valid 384-dimensional embeddings.

The CSV training aliases for the final two canonical features are:

- `semantic_similarity`
- `knowledge_graph_similarity`

## 4. v3 dataset recomputation

The v3 recomputation bug involving set/dictionary subtraction was fixed.

The resulting `correlation-dataset-v3` contains:

- 16,785 eligible pairs.
- 2,266 positive pairs.
- 14,519 negative pairs.
- 814 represented reports.
- Pair IDs preserved.
- Labels preserved.
- Label evidence preserved.
- Six canonical features preserved.
- `correlation-features-v1` preserved.

The v3 dataset SHA-256 is:

```text
72ac59730e14eaa8307434b3f81c2aff19e963eaa15458e7696695e1d69e7749
```

## 5. Campaign and incident grouping investigation

Explicit campaign metadata was inspected across:

- Original CTI-EACL24 metadata.
- Source documents.
- Silver-label evidence.
- Existing Neo4j graph relationships.

Reliable campaign identifiers could not be recovered for all pairs.

Conservative grouping based on campaign names and cross-source evidence caused:

- Severe transitive over-merging.
- Explicit negative conflicts inside merged groups.
- Unresolved pairs.
- No defensible campaign/incident partition for all rows.

Positive pairs were investigated as possible grouping links. Their transitive closure
was not accepted as ground truth because it could merge unrelated reports.

The conclusion was that a leakage-safe campaign-grouped 70:15:15 split is infeasible
for the current dataset. Pair-level experiments therefore document that campaign
leakage cannot be ruled out.

Report:

```text
backend/training/correlation/CAMPAIGN_GROUP_RECONSTRUCTION_REPORT.md
```

## 6. Exploratory pair-level training

Because campaign-grouped splitting was infeasible, a clearly labelled exploratory
pair-level experiment was run using fixed seed:

```text
20261117
```

Split sizes:

- Train: 11,749.
- Validation: 2,518.
- Test: 2,518.

Models:

- Logistic Regression.
- Random Forest.
- XGBoost when available.

XGBoost was unavailable in the selected CPU environment.

The original exploratory Random Forest test result was:

| Metric | Value |
|---|---:|
| Precision | 0.4508 |
| Recall | 0.5118 |
| F1 | 0.4793 |
| PR-AUC | 0.5330 |
| ROC-AUC | 0.7884 |
| FPR | 0.0973 |

The result measures agreement with weak/silver labels. It does not establish
campaign-independent generalization or independently verified real-world accuracy.

## 7. Advanced model optimization

The following CPU-compatible approaches were evaluated:

- Logistic Regression with class weighting.
- Random Forest.
- Extra Trees.
- HistGradientBoosting.
- Missing-indicator variants.
- Feature ablations.
- Validation-only threshold tuning.
- Optional probability calibration investigation.
- XGBoost when available.

Extra Trees was selected by validation in the advanced experiment.

Test result:

| Metric | Value |
|---|---:|
| F1 | 0.4823 |
| PR-AUC | 0.5447 |
| ROC-AUC | 0.7914 |
| FPR | 0.0895 |

The target F1 of 0.70 was not reached.

Report:

```text
backend/training/correlation/ADVANCED_MODEL_OPTIMIZATION_REPORT.md
```

## 8. ATT&CK and behavioural feature improvement

### ATT&CK root cause

The v3 feature recomputation retained explicit ATT&CK IDs but did not invoke the
existing MITRE mapping service during recomputation.

The existing ATT&CK mapper was reused against:

- Report text.
- Explicit MITRE ATT&CK references.
- Lexical technique-name evidence.

Entity-to-technique inference was disabled to avoid unsupported relationships.

### Coverage changes

ATT&CK missingness changed from:

```text
99.8213% -> 0.6136%
```

Behavioural missingness changed from:

```text
24.7125% -> 22.7703%
```

The improvements were source-grounded and retained evidence, extraction method, and
confidence. Lexical ATT&CK matching remains a limitation because generic terms can
produce broad matches and are not equivalent to expert annotation.

### v4 dataset

The new versioned dataset is:

```text
backend/data/correlation/processed/v4_feature_improvement/
```

It contains:

- `silver_correlation_pairs.csv`
- `feature_generation_metadata.json`
- `feature_evidence.jsonl`
- `report_extraction_evidence.jsonl`
- `label_evidence.csv`
- `report_embeddings.jsonl`

The v4 dataset contains the same 16,785 pair IDs and labels as v3 and retains
`correlation-features-v1`.

The v4 dataset SHA-256 is:

```text
e1ee2c15ebec9b55dd33fc87b07ea683dd33fc87b07ea683ddab39bdd21b65c398d4d9ef8168b24a
```

Reports:

```text
backend/training/correlation/FEATURE_IMPROVEMENT_REPORT.md
backend/training/correlation/V4_TRAINING_COMPARISON_REPORT.md
```

## 9. v3/v4 model comparison

The exact saved v3 split assignments were reused by pair ID.

Both datasets:

- Contain 16,785 rows.
- Contain identical pair IDs.
- Contain identical labels.
- Retain the six canonical features.
- Use `correlation-features-v1`.

Same-protocol Random Forest results:

| Dataset | F1 | PR-AUC | ROC-AUC | FPR |
|---|---:|---:|---:|---:|
| v3 | 0.4908 | 0.5396 | 0.7891 | 0.0698 |
| v4 | 0.4818 | 0.5475 | 0.7940 | 0.1028 |

ATT&CK feature importance increased from:

```text
0.000482 -> 0.166945
```

Ranking metrics improved modestly, but F1 declined. Improved feature coverage did
not automatically improve pair classification.

## 10. F1 improvement experiment

An evidence-weighted experiment was created to investigate:

- False-positive and false-negative behavior.
- Evidence-backed hard negatives.
- Confidence-weighted training.
- Positive-unlabeled learning feasibility.
- Raw entity and indicator overlaps.
- Additional CPU-compatible models.

The weak-supervision audit found:

- All 16,785 labels matched deterministic high-confidence rules.
- 14,519 negative rows matched high-confidence negative rules.
- 2,266 positive rows matched high-confidence positive rules.
- No genuinely unlabeled subset was available for a valid PU experiment.

An initial v1 run produced a perfect score, but it was rejected as invalid because
label-derived campaign and hard-negative fields were included as predictors.

The corrected leakage-safe experiment is:

```text
backend/data/correlation/experiments/f1_improvement_v3/
```

The leakage-safe model uses:

- The six canonical features.
- `shared_actor`
- `shared_malware`
- `shared_tool`
- `shared_technique`
- `shared_indicator`
- `cross_vendor`

The model does not use label-derived campaign-reference, label-confidence, or
hard-negative fields as inference predictors.

The selected model is:

```text
Random Forest
configuration: depth_None_leaf_1
threshold: 0.35
```

Final held-out test results:

| Metric | Value |
|---|---:|
| Precision | 0.7584 |
| Recall | 0.6000 |
| F1 | 0.6700 |
| PR-AUC | 0.7448 |
| ROC-AUC | 0.8874 |
| FPR | 0.0298 |

Confusion matrix:

```text
[[2113, 65],
 [136, 204]]
```

The target F1 of 0.70 was not reached. The result remains agreement with silver
labels only, and campaign-independent generalization remains unverified.

Artifacts:

- `models/random_forest.joblib`
- `config.json`
- `metrics.json`
- `improved_dataset.csv`
- `improved_pair_evidence.csv`
- `split_assignments.csv`
- `F1_IMPROVEMENT_REPORT.md`

## 11. Application model integration

The selected Random Forest was integrated without retraining or modifying the
experiment artifacts.

### Predictor integration

Added:

```text
backend/app/ml/correlation/evidence_model.py
```

The predictor:

- Loads the saved joblib artifact.
- Loads the experiment configuration.
- Loads the saved metrics and selected threshold.
- Validates the selected model family.
- Validates the `correlation-features-v1` schema.
- Validates the exact 12-input ordering.
- Produces a probability in `[0, 1]`.
- Retains raw evidence and model feature traces.
- Raises explicit errors for missing or invalid artifacts.

Exact model feature order:

1. `temporal_similarity`
2. `entity_relationship_similarity`
3. `behavioural_similarity`
4. `attack_technique_similarity`
5. `semantic_similarity`
6. `knowledge_graph_similarity`
7. `shared_actor`
8. `shared_malware`
9. `shared_tool`
10. `shared_technique`
11. `shared_indicator`
12. `cross_vendor`

The runtime uses the same
`training.correlation.weak_supervision.extract_evidence` implementation as the
experiment for raw overlap extraction.

### Backend integration

Modified:

- `backend/app/ml/correlation/base.py`
- `backend/app/ml/correlation/predictor_factory.py`
- `backend/app/core/config.py`
- `backend/app/correlation/orchestration.py`
- `backend/app/api/v1/correlations.py`
- `backend/app/api/v1/model.py`

The correlation orchestration now:

- Builds the existing six canonical features.
- Builds the six raw report-evidence overlap inputs.
- Runs the saved Random Forest.
- Applies the saved validation threshold by default.
- Stores relatedness probability.
- Stores binary relationship status.
- Stores canonical feature evidence.
- Stores raw overlap evidence and model feature traces.
- Keeps candidate relationships subject to analyst review.

The existing baseline predictor remains the default in application settings to
preserve backward compatibility. Activation of the integrated model is explicit:

```text
CORRELATION_PREDICTOR=trained_evidence
```

The example configuration points to:

```text
data/correlation/experiments/f1_improvement_v3/models/random_forest.joblib
data/correlation/experiments/f1_improvement_v3/config.json
data/correlation/experiments/f1_improvement_v3/metrics.json
```

### Dashboard integration

Modified:

- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`

The Correlations page displays:

- Relatedness probability.
- Predicted relationship status.
- Six canonical feature values.
- Predictor version and threshold.
- Raw evidence/model feature trace.
- A visible analyst-review warning that the result is a candidate correlation,
  not verified campaign attribution.

### Documentation

Modified:

- `MODEL_INTEGRATION.md`
- `artifacts/correlation/README.md`
- `.env.example`

The documentation describes:

- Model activation.
- Artifact paths.
- Feature order.
- Missing-value policy.
- Raw evidence inputs.
- Saved threshold.
- Error behavior.
- Analyst-review limitations.

## 12. Verification completed

### Focused model and correlation tests

The focused tests cover:

- Model loading.
- Missing artifact handling.
- Feature order validation.
- Raw evidence extraction.
- Runtime feature parity.
- Probability generation.
- Existing predictor behavior.
- Correlation orchestration.

Focused result:

```text
14 passed
```

### Backend regression suite

Final backend result:

```text
83 passed, 1 skipped
```

### Frontend build

Final frontend production build completed successfully with TypeScript checking and
Vite bundling.

### Runtime feature parity

The runtime raw evidence features were compared against the experiment's
`improved_pair_evidence.csv` for an identical report pair.

Result:

```text
feature_parity=PASS
```

The saved model loaded successfully and returned:

```text
model_version=f1-improvement-v3
threshold=0.35
```

## 13. Remaining limitations and operational notes

1. Campaign-level leakage cannot be ruled out because a defensible campaign-grouped
   split was not feasible.
2. All training labels are weak/silver labels rather than independently verified
   ground truth.
3. The final F1 of `0.6700` is below the requested approximate target of `0.70`.
4. The model is not production-ready and does not establish independently verified
   real-world campaign accuracy.
5. ATT&CK lexical mapping can be broad for generic terms and should remain subject
   to analyst review.
6. Qdrant remained unavailable during the feature work; missing semantic evidence
   follows the existing neutral missing-data policy.
7. The integrated model requires `CORRELATION_PREDICTOR=trained_evidence` to be
   enabled. The baseline remains the default for compatibility.
8. The model expects the saved experiment artifact and its matching configuration
   and metrics files to remain available at the configured paths.
9. Shared actors, malware, tools, or ATT&CK techniques are evidence features but are
   not proof of common campaign membership.
10. Correlation output is a candidate relationship for analyst review and approval,
    not an automatic attribution.

## 14. Key source files and reports

### Correlation and feature implementation

- `backend/app/correlation/service.py`
- `backend/app/correlation/feature_schema.py`
- `backend/app/correlation/behavioural.py`
- `backend/app/correlation/orchestration.py`
- `backend/training/correlation/weak_supervision.py`
- `backend/training/correlation/recompute_v3.py`
- `backend/training/correlation/recompute_feature_improvements.py`

### Model and experiment implementation

- `backend/training/correlation/run_exploratory_training.py`
- `backend/training/correlation/run_advanced_optimization.py`
- `backend/training/correlation/run_v4_training_comparison.py`
- `backend/training/correlation/run_f1_improvement_experiment.py`
- `backend/app/ml/correlation/evidence_model.py`
- `backend/app/ml/correlation/predictor_factory.py`

### Reports

- `backend/training/correlation/DATASET_READINESS_V3.md`
- `backend/training/correlation/CAMPAIGN_GROUP_RECONSTRUCTION_REPORT.md`
- `backend/training/correlation/EXPLORATORY_TRAINING_REPORT.md`
- `backend/training/correlation/ADVANCED_MODEL_OPTIMIZATION_REPORT.md`
- `backend/training/correlation/FEATURE_IMPROVEMENT_REPORT.md`
- `backend/training/correlation/V4_TRAINING_COMPARISON_REPORT.md`
- `backend/data/correlation/experiments/f1_improvement_v3/F1_IMPROVEMENT_REPORT.md`
- `MODEL_INTEGRATION.md`

