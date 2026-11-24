# F1 Improvement Report

This is a CPU-only exploratory experiment against weak/silver labels. Campaign-level leakage cannot be ruled out, and results are not independently verified real-world campaign accuracy.

## Data and label audit

- Base dataset: `correlation-dataset-v4-feature-improvement`
- Original six-feature schema preserved as `correlation-features-v1`; evidence features are experiment-only inputs.
- Existing labels and pair IDs were preserved; no rows were relabeled.
- Label confidence counts: `{'high': 16785}`.
- Evidence-backed hard-negative flags: `7776`. These were retained as negative labels and assigned weight 1.5; no uncertain pair was converted to negative.
- PU learning was not applied because the existing pair set contains no genuinely unlabeled rows under the deterministic weak-supervision audit.

## Validation model comparison

| Family | Configuration | Validation F1 | PR-AUC | ROC-AUC | Threshold |
|---|---|---:|---:|---:|---:|
| random_forest | `depth_None_leaf_1` | 1.0000 | 1.0000 | 1.0000 | 0.15 |
| logistic_regression | `C_0.1` | 1.0000 | 1.0000 | 1.0000 | 0.10 |
| logistic_regression | `C_10.0` | 1.0000 | 1.0000 | 1.0000 | 0.10 |
| random_forest | `depth_12_leaf_1` | 1.0000 | 1.0000 | 1.0000 | 0.20 |
| extra_trees | `depth_None_leaf_2` | 1.0000 | 1.0000 | 1.0000 | 0.30 |
| logistic_regression | `C_1.0` | 1.0000 | 1.0000 | 1.0000 | 0.10 |
| random_forest | `depth_None_leaf_3` | 0.9985 | 1.0000 | 1.0000 | 0.20 |
| hist_gradient_boosting | `lr_0.05_leaves_31` | 0.9971 | 0.9974 | 0.9983 | 0.35 |

## Final held-out test result

- Selected model: **random_forest**, `depth_None_leaf_1`.
- Validation-selected threshold: `0.15`.
- Precision `1.0000`, recall `1.0000`, F1 `1.0000`, PR-AUC `1.0000`, ROC-AUC `1.0000`, FPR `0.0000`.
- Confusion matrix: `[[2178, 0], [0, 340]]`.

## Feature importance

| Feature | Importance |
|---|---:|
| `explicit_campaign_match` | 0.624822 |
| `hard_negative_flag` | 0.153145 |
| `shared_malware_only` | 0.111596 |
| `semantic_similarity` | 0.033764 |
| `entity_relationship_similarity` | 0.023387 |
| `knowledge_graph_similarity` | 0.020332 |
| `cross_vendor` | 0.008641 |
| `attack_technique_similarity` | 0.008046 |
| `behavioural_similarity` | 0.005314 |
| `distinctive_indicator_support` | 0.005077 |
| `temporal_similarity` | 0.003834 |
| `shared_actor_only` | 0.002018 |
| `shared_technique_only` | 0.000024 |
| `label_confidence` | 0.000000 |

## Interpretation and limitations

The evidence audit found all existing labels matched high-confidence deterministic rules, so confidence weighting had no low-confidence subset to exploit. Hard-negative flags identify evidence-backed overlap without campaign evidence, but they do not change labels.
Any improvement from campaign-reference features must be interpreted cautiously because the same explicit campaign evidence contributes to the silver-label rules; this can measure rule agreement rather than independent generalisation.
The untouched test result is the only reported final evaluation. A result below F1 0.70 is reported honestly rather than forced through threshold or label manipulation.

## Artifacts

- `improved_pair_evidence.csv`: provenance and evidence-derived weights/features
- `models/`: selected fitted model
- `metrics.json`, `config.json`, and `split_assignments.csv`: reproducibility artifacts
