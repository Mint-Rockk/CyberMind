# Feature Improvement Report

## Scope

This report documents an isolated recomputation of `correlation-dataset-v4-feature-improvement`.
The original v3 dataset, silver labels, pair IDs, and `correlation-features-v1` six-value
schema were not modified. No model was trained.

## Root-cause findings

- v3 populated `attack_techniques` only from explicit `T####` references retained during
  dataset preparation. The existing MITRE mapping service was not invoked by
  `recompute_v3.py`, so report text containing technique names or aliases was ignored.
- v3 used `deterministic_behaviour_lexicon_v1`. Reports without one of its narrow phrases
  therefore produced an explicitly unavailable behavioural representation and the
  production neutral value `0.5`.

## Implemented changes

### ATT&CK

- Reused the existing `AttackDataset` and `find_mapping_candidates` implementation.
- Downloaded and recorded the official Enterprise ATT&CK STIX dataset version
  `enterprise-attack-20.1`.
- Applied only:
  - explicit ATT&CK IDs found in report title/body; and
  - lexical matches to ATT&CK technique names or aliases in report text.
- Entity-to-technique relationship inference was disabled. Shared actors, malware, tools,
  or techniques were not used to infer campaign membership.
- Every mapped technique retains its external ID, name, confidence, mapping method, status,
  and source sentence in `report_extraction_evidence.jsonl`.

### Behaviour

- Extended the existing deterministic lexicon to cover additional explicit procedures,
  including user execution, downloads, process injection, startup persistence, browser
  credential theft, system/network discovery, remote services, file search, staged data,
  and artifact clearing.
- Each behaviour retains its matched source sentence, character offsets, extraction method,
  and confidence.
- Reports without supported evidence remain unavailable; no synthetic behaviour or zero
  replacement was introduced.

## Coverage comparison

The comparison uses the 814 reports represented in the v3 pair dataset and all 16,785
original pairs.

| Measure | v3 | v4 improved | Change |
|---|---:|---:|---:|
| Reports with ATT&CK techniques | 12/814 (1.47%) | 809/814 (99.39%) | +797 reports |
| ATT&CK feature missingness | 16,755/16,785 (99.8213%) | 103/16,785 (0.6136%) | -99.2077 percentage points |
| Reports with behavioural evidence | Not retained as a v3 report-level statistic | 645/814 (79.24%) | report-level baseline unavailable |
| Behavioural feature missingness | 4,148/16,785 (24.7125%) | 3,822/16,785 (22.7703%) | -1.9422 percentage points |

The ATT&CK improvement is substantial because the mapper now consumes evidence already
present in report text. Behavioural improvement is intentionally modest: the remaining
reports do not contain a supported explicit procedure phrase under the deterministic
extractor.

## Dataset and preservation checks

- Dataset version: `correlation-dataset-v4-feature-improvement`
- Feature schema: unchanged `correlation-features-v1`
- Pair count: 16,785
- Labels: 2,266 positive and 14,519 negative
- Pair IDs: preserved from v3
- Labels: preserved from v3
- Source v3 SHA-256:
  `72ac59730e14eaa8307434b3f81c2aff19e963eaa15458e7696695e1d69e7749`
- Neo4j coverage: 12,095 report nodes; existing graph relationships reused
- Unsupported ATT&CK references: 2 reports, retained as unsupported evidence rather than
  being mapped speculatively

The six model inputs remain in the original order:

1. `temporal_similarity`
2. `entity_relationship_similarity`
3. `behavioural_similarity`
4. `attack_technique_similarity`
5. `semantic_embedding_similarity`
6. `knowledge_graph_relationship_similarity`

Availability and provenance are stored outside the six-value CSV in
`report_extraction_evidence.jsonl` and `feature_evidence.jsonl`. Missing feature values
continue to materialize as neutral `0.5` only under the existing v1 policy, with
`available=false` evidence retained.

## Remaining limitations

- Lexical ATT&CK mapping is evidence-backed text matching, but it is not equivalent to
  expert annotation and can still produce false positives when a technique name is used
  descriptively rather than operationally.
- Two explicit ATT&CK references were unsupported by the downloaded ATT&CK version.
- Behavioural extraction remains deterministic and conservative; it does not infer a
  procedure from an actor, malware, tool, or technique association.
- Campaign/incident grouping remains infeasible, and no independent validation labels exist.
- This dataset has not been used for training in this task.

## Verification

- Focused correlation and ATT&CK mapping tests: **20 passed**.
- The new recomputation completed successfully against Neo4j and the preserved v3 inputs.
- Output directory:
  `backend/data/correlation/processed/v4_feature_improvement/`
