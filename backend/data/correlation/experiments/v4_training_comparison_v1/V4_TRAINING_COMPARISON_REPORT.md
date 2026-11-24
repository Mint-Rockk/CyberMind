# V4 Training Comparison Report

This is a CPU-only exploratory experiment against weak/silver labels. Campaign-level leakage cannot be ruled out because campaign/incident grouping was infeasible. Results are not campaign-independent or independently verified real-world accuracy.

## Integrity checks

- Pair IDs and labels match v3 exactly: **True**
- v3 rows: 16785; v4 rows: 16785
- Feature schema: `correlation-features-v1`
- Random seed: `20261117`; split source: preserved v3 pair-level assignments
- CPU-only: yes; test data was not used for selection or threshold tuning

## Split counts

| Dataset | Split | Rows | Negative | Positive |
|---|---|---:|---:|---:|
| v3 | test | 2518 | 2178 | 340 |
| v3 | train | 11749 | 10163 | 1586 |
| v3 | validation | 2518 | 2178 | 340 |
| v4 | test | 2518 | 2178 | 340 |
| v4 | train | 11749 | 10163 | 1586 |
| v4 | validation | 2518 | 2178 | 340 |

## Feature distribution and missingness comparison

| Feature | v3 mean | v4 mean | v3 missing % | v4 missing % |
|---|---:|---:|---:|---:|
| `temporal_similarity` | 0.034436 | 0.034436 | 5.6002 | 5.6002 |
| `entity_relationship_similarity` | 0.057380 | 0.057380 | 0.0000 | 0.0000 |
| `behavioural_similarity` | 0.267382 | 0.244017 | 24.7125 | 22.7703 |
| `attack_technique_similarity` | 0.499315 | 0.302741 | 99.8213 | 0.6136 |
| `semantic_similarity` | 0.742816 | 0.742816 | 0.0000 | 0.0000 |
| `knowledge_graph_similarity` | 0.070136 | 0.070136 | 0.0000 | 0.0000 |

## Selected-model test comparison

| Dataset | Model | Precision | Recall | F1 | PR-AUC | ROC-AUC | FPR | Threshold |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| v3 | random_forest (depth_None_leaf_1) | 0.5128 | 0.4706 | 0.4908 | 0.5396 | 0.7891 | 0.0698 | 0.30 |
| v4 | random_forest (depth_None_leaf_3) | 0.4442 | 0.5265 | 0.4818 | 0.5475 | 0.7940 | 0.1028 | 0.35 |

## Validation model selection

| Dataset | Family | Configuration | Validation F1 | Validation PR-AUC | Threshold |
|---|---|---|---:|---:|---:|
| v3 | random_forest | `depth_None_leaf_1` | 0.5064 | 0.5310 | 0.30 |
| v3 | random_forest | `depth_None_leaf_3` | 0.4961 | 0.5312 | 0.45 |
| v3 | random_forest | `depth_12_leaf_1` | 0.4922 | 0.5226 | 0.50 |
| v3 | logistic_regression | `C_10.0` | 0.4448 | 0.4347 | 0.60 |
| v3 | logistic_regression | `C_1.0` | 0.4441 | 0.4346 | 0.60 |
| v3 | logistic_regression | `C_0.1` | 0.4432 | 0.4355 | 0.60 |
| v4 | random_forest | `depth_None_leaf_3` | 0.5007 | 0.5466 | 0.35 |
| v4 | random_forest | `depth_None_leaf_1` | 0.4985 | 0.5459 | 0.25 |
| v4 | random_forest | `depth_12_leaf_1` | 0.4860 | 0.5341 | 0.50 |
| v4 | logistic_regression | `C_10.0` | 0.4496 | 0.4346 | 0.55 |
| v4 | logistic_regression | `C_1.0` | 0.4490 | 0.4347 | 0.55 |
| v4 | logistic_regression | `C_0.1` | 0.4474 | 0.4354 | 0.55 |

## V4 feature importance

| Feature | Importance |
|---|---:|
| `attack_technique_similarity` | 0.166945 |
| `behavioural_similarity` | 0.088018 |
| `entity_relationship_similarity` | 0.213221 |
| `knowledge_graph_relationship_similarity` | 0.201259 |
| `semantic_embedding_similarity` | 0.312318 |
| `temporal_similarity` | 0.018239 |

## Interpretation

- Test F1 changed from `0.4908` on v3 to `0.4818` on v4 (-0.0090); v4 did not improve F1.
- Test PR-AUC changed from `0.5396` to `0.5475` (+0.0079) and ROC-AUC changed from `0.7891` to `0.7940` (+0.0049); ranking improved modestly while the selected threshold produced lower F1.
- ATT&CK feature importance increased from `0.000482` to `0.166945`. Behavioural importance changed from `0.093756` to `0.088018`.
The coverage improvement therefore made ATT&CK information usable to the model, but did not by itself establish better classification at the selected operating threshold. Any metric change remains an exploratory weak-label result and does not prove campaign-independent generalisation.

## Artifacts

- `v3/` and `v4/`: separately saved selected model artifacts
- `metrics.json`: validation candidates, selected models, test metrics and importance
- `config.json`: dataset hashes, split hash and reproducibility settings
