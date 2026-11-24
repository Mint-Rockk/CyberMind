# F1 Improvement Report

This is a CPU-only exploratory experiment against weak/silver labels. Campaign-level leakage cannot be ruled out, and results are not independently verified real-world campaign accuracy.

## Data and label audit

- Base dataset: `correlation-dataset-v4-feature-improvement`
- Original six-feature schema preserved as `correlation-features-v1`; raw overlap features are experiment-only inputs.
- Existing labels and pair IDs were preserved; no rows were relabeled.
- Label confidence counts: `{'high': 16785}`.
- Evidence-backed hard-negative flags: `7776`. These were retained as negative labels and assigned weight 1.5; no uncertain pair was converted to negative.
- PU learning was not applied because the existing pair set contains no genuinely unlabeled rows under the deterministic weak-supervision audit.

## Comparison with previous baselines

| Experiment | Test F1 | PR-AUC | ROC-AUC | FPR |
|---|---:|---:|---:|---:|
| v3 Random Forest | 0.4908 | 0.5396 | 0.7891 | 0.0698 |
| v4 Random Forest | 0.4818 | 0.5475 | 0.7940 | 0.1028 |
| leakage-safe v3 selected model | 0.6700 | 0.7448 | 0.8874 | 0.0298 |

## Validation model comparison

| Family | Configuration | Validation F1 | PR-AUC | ROC-AUC | Threshold |
|---|---|---:|---:|---:|---:|
| random_forest | `depth_None_leaf_1` | 0.6700 | 0.7451 | 0.8971 | 0.35 |
| random_forest | `depth_None_leaf_3` | 0.6635 | 0.7405 | 0.8987 | 0.50 |
| extra_trees | `depth_None_leaf_2` | 0.6571 | 0.7401 | 0.8978 | 0.60 |
| hist_gradient_boosting | `lr_0.05_leaves_31` | 0.6519 | 0.7404 | 0.9018 | 0.35 |
| random_forest | `depth_12_leaf_1` | 0.6448 | 0.7113 | 0.8881 | 0.55 |
| logistic_regression | `C_0.1` | 0.6167 | 0.6723 | 0.8588 | 0.75 |
| logistic_regression | `C_10.0` | 0.6141 | 0.6732 | 0.8592 | 0.70 |
| logistic_regression | `C_1.0` | 0.6141 | 0.6730 | 0.8591 | 0.70 |

## Final held-out test result

- Selected model: **random_forest**, `depth_None_leaf_1`.
- Validation-selected threshold: `0.35`.
- Precision `0.7584`, recall `0.6000`, F1 `0.6700`, PR-AUC `0.7448`, ROC-AUC `0.8874`, FPR `0.0298`.
- Confusion matrix: `[[2113, 65], [136, 204]]`.
- Validation confusion matrix at the selected threshold: `[[2121, 57], [140, 200]]` (FP=57, FN=140).

## Feature importance

| Feature | Importance |
|---|---:|
| `semantic_similarity` | 0.204526 |
| `knowledge_graph_similarity` | 0.136237 |
| `entity_relationship_similarity` | 0.132733 |
| `attack_technique_similarity` | 0.124971 |
| `shared_tool` | 0.114611 |
| `behavioural_similarity` | 0.068640 |
| `shared_malware` | 0.065459 |
| `shared_actor` | 0.060764 |
| `shared_indicator` | 0.054085 |
| `cross_vendor` | 0.022294 |
| `temporal_similarity` | 0.015351 |
| `shared_technique` | 0.000328 |

## Interpretation and limitations

The evidence audit found all existing labels matched high-confidence deterministic rules, so confidence weighting had no low-confidence subset to exploit. Hard-negative flags identify evidence-backed overlap without campaign evidence, but they do not change labels.
Campaign-reference, distinctive-indicator, hard-negative, and confidence fields are retained only as provenance/audit fields and were excluded from model inputs because they overlap with silver-label rules. The model uses raw report evidence overlaps and the six canonical features.
The v1 run produced a perfect score because label-derived campaign and hard-negative fields were included as predictors; that run is invalid for performance claims and is superseded by this leakage-safe rerun.
The leakage-safe rerun improved test F1 over the prior v3/v4 baselines but did not reach 0.70. This is agreement with silver labels only; campaign-independent generalisation and independently verified real-world accuracy remain unestablished.
The untouched test result is the only reported final evaluation. A result below F1 0.70 is reported honestly rather than forced through threshold or label manipulation.

## Artifacts

- `improved_dataset.csv`: unchanged v4 dataset copied into this experiment
- `improved_pair_evidence.csv`: provenance, raw evidence features, and evidence-derived training weights
- `models/`: selected fitted model
- `metrics.json`, `config.json`, and `split_assignments.csv`: reproducibility artifacts
