# Advanced Model Optimization Report

## Scope and evaluation integrity

This is a CPU-only exploratory optimization against weak/silver labels. The original v3 dataset, labels, pair IDs, six feature values, exploratory split, and exploratory artifacts were not modified.
Campaign-level leakage cannot be ruled out because campaign/incident grouping was infeasible; metrics may be optimistic and are not campaign-independent or independently verified real-world accuracy.

## Configuration

- Dataset: `correlation-dataset-v3` (`72ac59730e14eaa8307434b3f81c2aff19e963eaa15458e7696695e1d69e7749`)
- Schema: `correlation-features-v1`
- Seed: `20261117`; split: preserved stratified pair-level 70:15:15
- CPU-only: yes; test set was not used for model or threshold selection
- Missingness: v3 neutral `0.5` policy preserved; optional indicators only identify documented neutral materialization

## Counts

| Split | Rows | Negative | Positive |
|---|---:|---:|---:|
| train | 11749 | 10163 | 1586 |
| validation | 2518 | 2178 | 340 |
| test | 2518 | 2178 | 340 |

## Validation model/configuration comparison

| Family | Configuration | Feature variant | F1 | PR-AUC | ROC-AUC | Threshold |
|---|---|---|---:|---:|---:|---:|
| extra_trees | `depth_None_leaf_2` | `all_features` | 0.5142 | 0.5402 | 0.8110 | 0.50 |
| extra_trees | `depth_16_leaf_2` | `all_features_with_missing_indicators` | 0.5105 | 0.5343 | 0.8014 | 0.50 |
| extra_trees | `depth_None_leaf_2` | `all_features_with_missing_indicators` | 0.5074 | 0.5404 | 0.8075 | 0.50 |
| random_forest | `depth_None_leaf_1_features_sqrt` | `all_features` | 0.5064 | 0.5322 | 0.7981 | 0.30 |
| random_forest | `depth_None_leaf_1_features_sqrt` | `all_features_with_missing_indicators` | 0.5048 | 0.5288 | 0.7914 | 0.30 |
| random_forest | `depth_None_leaf_2_features_sqrt` | `all_features` | 0.5042 | 0.5340 | 0.8036 | 0.35 |
| extra_trees | `depth_None_leaf_1` | `all_features_with_missing_indicators` | 0.5008 | 0.5156 | 0.7856 | 0.35 |
| extra_trees | `depth_16_leaf_2` | `all_features` | 0.5000 | 0.5331 | 0.8029 | 0.50 |
| random_forest | `depth_None_leaf_2_features_sqrt` | `all_features_with_missing_indicators` | 0.4977 | 0.5348 | 0.8015 | 0.40 |
| extra_trees | `depth_None_leaf_1` | `all_features` | 0.4904 | 0.5157 | 0.7914 | 0.40 |
| hist_gradient_boosting | `lr_0.05_leaves_31_l2_5.0` | `all_features_with_missing_indicators` | 0.4899 | 0.5187 | 0.7992 | 0.60 |
| extra_trees | `depth_16_leaf_1` | `all_features_with_missing_indicators` | 0.4897 | 0.5304 | 0.7882 | 0.50 |
| extra_trees | `depth_16_leaf_1` | `all_features` | 0.4869 | 0.5350 | 0.7950 | 0.50 |
| random_forest | `depth_16_leaf_1_features_sqrt` | `all_features` | 0.4868 | 0.5244 | 0.7949 | 0.40 |
| hist_gradient_boosting | `lr_0.1_leaves_15_l2_1.0` | `all_features` | 0.4838 | 0.5023 | 0.7971 | 0.55 |
| hist_gradient_boosting | `lr_0.1_leaves_15_l2_1.0` | `all_features_with_missing_indicators` | 0.4837 | 0.5116 | 0.7973 | 0.60 |
| hist_gradient_boosting | `lr_0.05_leaves_31_l2_1.0` | `all_features_with_missing_indicators` | 0.4831 | 0.5043 | 0.7964 | 0.55 |
| hist_gradient_boosting | `lr_0.05_leaves_15_l2_1.0` | `all_features` | 0.4830 | 0.5084 | 0.8001 | 0.55 |
| random_forest | `depth_16_leaf_1_features_sqrt` | `all_features_with_missing_indicators` | 0.4811 | 0.5229 | 0.7927 | 0.40 |
| hist_gradient_boosting | `lr_0.05_leaves_31_l2_5.0` | `all_features` | 0.4807 | 0.5094 | 0.7983 | 0.60 |
| hist_gradient_boosting | `lr_0.05_leaves_31_l2_1.0` | `all_features` | 0.4757 | 0.5043 | 0.7994 | 0.55 |
| hist_gradient_boosting | `lr_0.05_leaves_15_l2_1.0` | `all_features_with_missing_indicators` | 0.4738 | 0.5071 | 0.7982 | 0.60 |
| random_forest | `depth_None_leaf_1_features_1.0` | `all_features` | 0.4717 | 0.5033 | 0.7837 | 0.40 |
| random_forest | `depth_None_leaf_1_features_1.0` | `all_features_with_missing_indicators` | 0.4685 | 0.5021 | 0.7839 | 0.35 |
| logistic_regression | `C_1.0` | `all_features_with_missing_indicators` | 0.4454 | 0.4346 | 0.7319 | 0.60 |
| logistic_regression | `C_10.0` | `all_features_with_missing_indicators` | 0.4454 | 0.4346 | 0.7319 | 0.60 |
| logistic_regression | `C_100.0` | `all_features_with_missing_indicators` | 0.4454 | 0.4345 | 0.7319 | 0.60 |
| logistic_regression | `C_100.0` | `all_features` | 0.4448 | 0.4347 | 0.7320 | 0.60 |
| logistic_regression | `C_10.0` | `all_features` | 0.4448 | 0.4347 | 0.7320 | 0.60 |
| logistic_regression | `C_1.0` | `all_features` | 0.4441 | 0.4346 | 0.7319 | 0.60 |
| logistic_regression | `C_0.1` | `all_features` | 0.4432 | 0.4355 | 0.7317 | 0.60 |
| logistic_regression | `C_0.1` | `all_features_with_missing_indicators` | 0.4412 | 0.4353 | 0.7316 | 0.55 |

## Selected model and unchanged test evaluation

- Selected by validation F1/PR-AUC/precision: **extra_trees**, `depth_None_leaf_2`, `all_features`.
- Validation threshold: `0.50`.

| Precision | Recall | F1 | PR-AUC | ROC-AUC | FPR |
|---:|---:|---:|---:|---:|---:|
| 0.4658 | 0.5000 | 0.4823 | 0.5447 | 0.7914 | 0.0895 |
- Confusion matrix: `[[1983, 195], [170, 170]]`.
- Original Random Forest F1: `0.4793`; optimized test F1: `0.4823`.
- Target F1 >= 0.70 achieved: **False**.

## Feature ablations (validation only)

| Removed feature | F1 | PR-AUC | Threshold |
|---|---:|---:|---:|
| `temporal_similarity` | 0.4870 | 0.5276 | 0.50 |
| `entity_relationship_similarity` | 0.4730 | 0.5051 | 0.55 |
| `behavioural_similarity` | 0.4838 | 0.5211 | 0.55 |
| `attack_technique_similarity` | 0.5046 | 0.5428 | 0.45 |
| `semantic_similarity` | 0.4189 | 0.4517 | 0.55 |
| `knowledge_graph_similarity` | 0.4812 | 0.4989 | 0.55 |

## Calibration, redundancy, and limitations

- No probability calibration was applied: the fixed validation data supported threshold tuning, but did not justify adding a calibration stage without an independent calibration set.
- Feature redundancy was investigated through six ablations and the documented neutral-value indicators; no source feature values were altered.
- This experiment does not establish real-world campaign-correlation accuracy or campaign-independent generalisation.

## Artifacts

- `models/`: selected fitted model
- `metrics.json`: all validation configurations, ablations, and one selected-model test evaluation
- `split_assignments.csv`, `config.json`, and `preprocessing.json`: reproducibility metadata
