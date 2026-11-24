# Exploratory Training Report

## Scope and warning

This is an exploratory pair-level CPU experiment against weak/silver labels. Campaign-level leakage cannot be ruled out because a defensible campaign/incident grouping was unavailable. Test metrics may therefore be optimistic and must not be interpreted as campaign-independent or independently verified real-world accuracy.

No original dataset, label, pair ID, or six-feature value was modified. No final production model is implied.

## Configuration

- Dataset: `correlation-dataset-v3`
- Feature schema: `correlation-features-v1`
- Features: `temporal_similarity, entity_relationship_similarity, behavioural_similarity, attack_technique_similarity, semantic_embedding_similarity, knowledge_graph_relationship_similarity`
- Random seed: `20261117`
- Split: stratified pair-level 70% train / 15% validation / 15% test
- CPU-only: yes
- Missing-data handling: retained v3 neutral `0.5` materialization; no feature was dropped or filled with an arbitrary zero
- Started: `recorded in metrics.json`

## Dataset and split counts

- Rows: 16785
- Labels: {'negative': 14519, 'positive': 2266}
- Source SHA-256: `72ac59730e14eaa8307434b3f81c2aff19e963eaa15458e7696695e1d69e7749`

| Split | Rows | Negative | Positive |
|---|---:|---:|---:|
| train | 11749 | 10163 | 1586 |
| validation | 2518 | 2178 | 340 |
| test | 2518 | 2178 | 340 |

## Model comparison on held-out test data

| Model | Precision | Recall | F1 | PR-AUC | ROC-AUC | FPR |
|---|---:|---:|---:|---:|---:|---:|
| logistic_regression | 0.4343 | 0.4471 | 0.4406 | 0.4369 | 0.7160 | 0.0909 |
| majority_class_baseline | 0.0000 | 0.0000 | 0.0000 | 0.1350 | 0.5000 | 0.0000 |
| random_forest | 0.4508 | 0.5118 | 0.4793 | 0.5330 | 0.7884 | 0.0973 |

### Test thresholds and confusion matrices

- `logistic_regression`: threshold `0.60`, confusion matrix `[[TN=1980, FP=198], [FN=188, TP=152]]`.
- `majority_class_baseline`: threshold `0.50`, confusion matrix `[[TN=2178, FP=0], [FN=340, TP=0]]`.
- `random_forest`: threshold `0.25`, confusion matrix `[[TN=1966, FP=212], [FN=166, TP=174]]`.

### Validation tuning results

| Model | Selected candidate | Threshold | Validation F1 | Validation PR-AUC |
|---|---|---:|---:|---:|
| logistic_regression | C_10.0 | 0.60 | 0.4448 | 0.4347 |
| majority_class_baseline | majority baseline | 0.50 | 0.0000 | 0.1350 |
| random_forest | depth_None_leaf_1 | 0.25 | 0.4979 | 0.5295 |

Selected model by validation F1/PR-AUC: **random_forest**.
Thresholds were selected on validation data only. The test set was read only for final evaluation.

## Limitations

- Labels are deterministic weak/silver labels, not independent ground truth.
- Pair-level stratification does not prevent reports, campaigns, or incidents from appearing across partitions.
- Campaign/incident grouping was tested and rejected because it produced transitive over-merging and explicit negative conflicts.
- XGBoost is included only when installed; unavailable estimators are recorded in `metrics.json`.
- Results do not establish campaign-independent generalisation or real-world campaign-correlation accuracy.

## Artifacts

- `models/`: versioned fitted model pipelines
- `split_assignments.csv`: fixed-seed row assignments and labels
- `preprocessing.json` and `preprocessing.joblib`: preprocessing metadata
- `config.json`: reproducibility configuration
- `metrics.json`: validation tuning and test metrics
