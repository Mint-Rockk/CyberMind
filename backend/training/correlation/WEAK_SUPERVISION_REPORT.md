# Weak Supervision Report

## Status

This is a provisional weak-supervision run, not manually verified ground
truth. No Random Forest was trained and no trained artifact was created.

The deterministic pipeline is implemented in
`backend/training/correlation/weak_supervision.py`. It reads the complete
normalized report text and metadata, analyzes the preserved 797,236 candidate
pairs, and writes provenance-bearing outputs under
`backend/data/correlation/weak_supervision/`.

## Exact run statistics

| Measure | Count |
|---|---:|
| Total pairs analyzed | 797,236 |
| Provisional positive labels | 2,531 |
| Provisional negative labels | 18,463 |
| Uncertain labels | 776,242 |
| High-confidence rule outcomes | 19,595 |
| Evidence-backed eligible high-confidence silver labels | 16,785 |
| Medium-confidence labels | 1,399 |
| Low-confidence/uncertain labels | 776,242 |
| Conflicting rule outcomes | 27 |
| High-confidence outcomes excluded for incomplete evidence | 2,810 |
| Evidence-complete pairs | 18,073 |
| Distinct campaign references in label evidence | 145 |
| Distinct report sources/vendors | 9 |
| Duplicate pairs | 0 |
| Reverse duplicate pairs | 0 |
| Eligible positive silver pairs | 2,266 |
| Eligible negative silver pairs | 14,519 |

The eligible silver class ratio is approximately 1:6.4 (positive:negative).
No duplication or synthetic balancing was performed.

## Deterministic labelling rules

### Positive

- **P1:** Both reports explicitly reference the same conservatively extracted
  named campaign or operation.
- **P2:** Both reports contain at least two shared distinctive indicators from
  different types, including a CVE, hash, or IP, plus incident context and
  publication dates within 90 days.
- **P3:** P1 evidence appears in different source vendors. P3 is recorded as
  corroboration metadata, not as a second independent copy of the same
  evidence.

### Negative

- **N1:** Each report explicitly names a different campaign/operation, with no
  shared distinctive indicator.
- **N2:** Different explicit named campaigns are more than one year apart and
  have incident context without shared distinctive evidence. This remains
  medium confidence.
- **N3:** Both reports contain explicit unrelated/separate-incident language.
  This remains medium confidence.

### Uncertain

- **U1:** Same actor attribution only.
- **U2:** Same malware only.
- **U3:** Same ATT&CK technique only.
- **U4:** Similar content without specific campaign evidence is not promoted by
  the deterministic run.
- **U5:** Insufficient evidence.
- **U6:** Conflicting attribution or conflicting positive/negative rules.
- **U7:** Missing or incomplete report content.

The same evidence excerpt is deduplicated within each pair. A shared actor,
malware, tool, vulnerability, or ATT&CK technique never independently creates
a positive label.

## Provenance and leakage controls

`labelling_evidence.csv` records report IDs, proposed label, confidence
category, method, matched rules, exact excerpts from both reports,
contradictory evidence, source references, campaign reference, schema version,
and generation timestamp. The evidence and rules are metadata only.

`processed/silver_correlation_pairs.csv` contains the six production feature
values plus pair IDs, label, and schema version. Report IDs, campaign
references, source names, paths, evidence, rule names, confidence, and
reasoning are never passed as model inputs. The production schema remains
`correlation-features-v1`.

Pair-level leakage risks remain:

- Reports can be syndicated or copied across vendors.
- Explicit campaign names used for labels must not be used as features.
- Source-aware and content-aware train/validation splitting is still required.
- Neutral missing values remain common for semantic, behavioral, and graph
  features; this run did not invent those representations.

## Optional LLM analysis

`llm_weak_supervision.py` provides a bounded, cached adapter for the existing
OpenAI-compatible provider. It validates the requested JSON fields, exact
evidence substrings, shared campaign references, and source references. The
default run made **zero** LLM calls (`llm_enabled=false`, budget zero).
No external provider was used and no provider confidence was treated as proof.

## Validation and limitations

The generated validation sample is
`backend/data/correlation/weak_supervision/validation_sample.csv`.
There is no independent campaign-level ground truth in CTI-EACL24, so silver
label quality and accuracy have **not** been independently established.
The apparent class balance and campaign diversity are rule-output statistics,
not performance metrics.

## Training-readiness decision

The dataset is **not ready for preliminary GPU training**. Although 16,785
evidence-backed provisional pairs passed the high-confidence rule gate, the
labels are unverified weak labels, 2,810 high-confidence outcomes lacked
complete evidence, the class distribution is imbalanced, and multiple feature
representations are missing/neutral. Training must wait for human validation
or an independently verified annotation source.
