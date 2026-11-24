# Cross-Source Correlation Model Integration

## Stable six-feature contract

The correlation model input is exactly six `float32` values in this order:

| Position | Feature name | Meaning |
|---:|---|---|
| 0 | `temporal_similarity` | Similarity of publication/activity windows. |
| 1 | `entity_relationship_similarity` | Jaccard similarity of normalized extracted entities. |
| 2 | `behavioural_similarity` | Jaccard similarity of normalized behaviors, tactics, and procedures supplied by upstream processing. |
| 3 | `attack_technique_similarity` | Jaccard similarity of ATT&CK technique identifiers. |
| 4 | `semantic_embedding_similarity` | Normalized cosine similarity of compatible, explicit embeddings. |
| 5 | `knowledge_graph_relationship_similarity` | Jaccard similarity of canonical `(subject, predicate, object)` graph relationships. |

The canonical definition is [`backend/app/correlation/feature_schema.py`](./backend/app/correlation/feature_schema.py).
The schema version is `correlation-features-v1`; feature names, order, and types must not change
without a new schema version and explicit model compatibility approval.

## Missing-value policy

Each feature service returns a normalized score in `[0, 1]`, an `available` flag, and evidence.
When required evidence is absent, the service returns a neutral `0.5` score with
`available=false` and a reason. Missing evidence is therefore not silently treated as
zero similarity or strong similarity.

The aggregated model vector uses the same neutral `0.5` value in the exact six positions.
Availability flags and evidence are retained outside the model input and must be retained
when constructing training examples. Training and inference must use the same policy.

## Integration boundary

Call `calculate_features(first, second)` from
[`backend/app/correlation/service.py`](./backend/app/correlation/service.py). Its
`FeatureVector.as_model_input()` method is the only supported model input. It returns
exactly six values and never adds missingness indicators or other features.

The services accept `DocumentRepresentation` or compatible mappings. Embeddings and
knowledge-graph relationships are inputs from their respective adapters; this phase does
not install an embedding model, connect to Neo4j, train a model, or fabricate predictions.

The Neo4j adapter now verifies the configured Bolt endpoint and database before graph
queries. Missing graph relationships remain explicit unavailable evidence according to
the existing neutral missing-data policy; a shared actor name alone does not create a
shared relationship or campaign claim.

## Predictor selection

Set `CORRELATION_PREDICTOR=baseline` for the transparent weighted heuristic, or
`CORRELATION_PREDICTOR=trained` to require an external artifact. In trained mode also set:

```text
CORRELATION_MODEL_ARTIFACT=artifacts/correlation/model.joblib
CORRELATION_MODEL_METADATA=artifacts/correlation/model_metadata.json
```

The trained artifact must be a trusted scikit-learn-compatible object with
`predict_proba`. XGBoost artifacts are supported when the supplying environment includes
XGBoost and the artifact exposes the same method; XGBoost is not installed by default.
The adapter validates the six feature names/order, `correlation-features-v1`, and
`neutral-missing-v1` preprocessing before making a prediction. Missing, invalid, or
incompatible trained artifacts raise an explicit unavailable/validation error and never
fall back to the baseline.

### Integrated f1-improvement-v3 predictor

Use `CORRELATION_PREDICTOR=trained_evidence` to load the verified CPU Random Forest
experiment directly:

```text
CORRELATION_MODEL_ARTIFACT=data/correlation/experiments/f1_improvement_v3/models/random_forest.joblib
CORRELATION_MODEL_METADATA=data/correlation/experiments/f1_improvement_v3/config.json
CORRELATION_MODEL_METRICS=data/correlation/experiments/f1_improvement_v3/metrics.json
```

Inference builds the canonical six-feature vector with the existing neutral `0.5`
missing-evidence policy, then appends raw report-evidence overlaps in this order:
`shared_actor`, `shared_malware`, `shared_tool`, `shared_technique`,
`shared_indicator`, `cross_vendor`. It reuses the same
`training.correlation.weak_supervision.extract_evidence` implementation used by the
experiment and applies the saved validation threshold `0.35`. Campaign-reference,
label-confidence, and hard-negative fields are not used at inference.

Correlation records retain the probability, threshold, canonical feature evidence,
raw overlap evidence, and model feature trace. The dashboard presents these as a
candidate correlation for analyst review, not verified campaign attribution or
production-ready independent accuracy.

## Required metadata format

`model_metadata.json` must contain these fields:

```json
{
  "model_name": "cross-source-threat-correlation",
  "model_version": "2026-11-16.1",
  "training_date": "2026-11-16",
  "feature_names": [
    "temporal_similarity",
    "entity_relationship_similarity",
    "behavioural_similarity",
    "attack_technique_similarity",
    "semantic_embedding_similarity",
    "knowledge_graph_relationship_similarity"
  ],
  "feature_schema_version": "correlation-features-v1",
  "preprocessing_version": "neutral-missing-v1",
  "training_dataset_reference": "replace-with-dataset-id",
  "evaluation_metrics": {
    "roc_auc": 0.0,
    "pr_auc": 0.0
  },
  "artifact_location": "artifacts/correlation/model.joblib"
}
```

Replace the example identity, dataset reference, and metrics with the independently
trained model's verified values. Do not describe the baseline as a trained model.

## CTI-EACL24 preparation status

The supplied CTI-EACL24 repository has been prepared by
`backend/training/correlation/prepare_dataset.py`. The preparation preserves
the production six-feature contract and writes normalized reports and pair
metadata under `backend/data/correlation/processed/`.

The dataset provides actor/group organization and report text, but the
inspection found no reliable campaign-level positive or negative pair labels.
All generated candidate pairs are `uncertain` and excluded from supervised
training. Analysts must complete `label_evidence.csv` with evidence-backed
decisions before a Random Forest artifact can be trained and registered.

## Weakly supervised silver data

`backend/training/correlation/weak_supervision.py` produces provisional labels
from explicit campaign/incident evidence. These labels are machine-generated
silver labels, not manually verified ground truth. The current run produced
16,785 eligible provisional labels (2,266 positive and 14,519 negative), but
there is no independent campaign-level validation set, so training remains
blocked.

The eligible file is
`backend/data/correlation/processed/silver_correlation_pairs.csv`. It contains
only the six production features, pair metadata, labels, and schema version.

## Current v3 readiness

The original silver file is preserved unchanged. v3 contains all 16,785
eligible pairs with the same IDs, labels, evidence, and
`correlation-features-v1` ordering. Neo4j covers all 12,095 reports used by
the dataset, while Qdrant remains unavailable; local pairwise embeddings do
not require Qdrant. Behavioural evidence is improved but remains missing for
24.7125% of pairs, and independent campaign validation is unavailable.
Therefore v3 is not ready for final supervised training or ground-truth
claims. See
[DATASET_READINESS_V3.md](backend/training/correlation/DATASET_READINESS_V3.md).
