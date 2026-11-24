# CTI-EACL24 Correlation Data Preparation Report

## Scope and reproducibility

Preparation was run with:

```powershell
$env:PYTHONPATH="backend"
backend\.venv\Scripts\python.exe -m training.correlation.prepare_dataset `
  --dataset-root backend\data\CTI-EACL24 `
  --output-root backend\data\correlation\processed
```

The original dataset is read-only input. Normalized copies and all derived
artifacts are under `backend/data/correlation/processed/`.

## Data quality

| Measure | Result |
|---|---:|
| Original local report files discovered | 15,735 |
| Successfully parsed unique reports | 12,095 |
| Empty reports excluded | 598 |
| Exact normalized duplicates excluded | 3,042 |
| Reports with usable UTC dates | 11,910 |
| Reports with extracted entities | 8,427 |
| Reports with explicit ATT&CK mappings/references | 81 |
| Candidate pairs generated from shared extracted evidence | 797,236 |
| Confirmed positive pairs | 0 |
| Confirmed negative pairs | 0 |
| Uncertain pairs | 797,236 |
| Pairs excluded from supervised training | 797,236 |

The candidate pairs are deterministic review candidates, not labels. They are
blocked on shared extracted CVEs, indicators, URLs, malware/tools, campaigns,
or explicit ATT&CK references. Actor/group names alone are intentionally not
candidate-label evidence.

## Metadata and provenance

`normalized_reports.jsonl` preserves original text, normalized text, original
filename, relative path, source/vendor, source URL, publication date, actor
group, content hash, extracted entity evidence, ATT&CK references, and
referenced URLs. `report_metadata.csv` provides a tabular index.

The preparation reuses CyberMind's normalization cleaning and deterministic
entity extraction. The local ATT&CK dataset is not present under the supplied
CTI-EACL24 directory, so no network download was performed. Explicit ATT&CK
IDs are preserved as extracted references; full ATT&CK name/alias mapping
requires the already-supported official dataset adapter and a locally supplied
dataset.

## Feature availability

The pair rows use the requested output aliases:

| Output column | CyberMind canonical feature |
|---|---|
| `temporal_similarity` | `temporal_similarity` |
| `entity_relationship_similarity` | `entity_relationship_similarity` |
| `behavioural_similarity` | `behavioural_similarity` |
| `attack_technique_similarity` | `attack_technique_similarity` |
| `semantic_similarity` | `semantic_embedding_similarity` |
| `knowledge_graph_similarity` | `knowledge_graph_relationship_similarity` |

The production model contract remains unchanged at
`correlation-features-v1`; only its six values may be passed to a model.

Missing feature evidence follows the production neutral-value policy and is
retained outside the model values:

- Temporal: missing in 57,119 candidate pairs.
- Entity relationship: missing in 0 candidate pairs.
- Behavioural: missing in 797,236 candidate pairs because the corpus does not
  provide a compatible behavior representation.
- ATT&CK technique: missing in 795,540 candidate pairs.
- Semantic: missing in 797,236 candidate pairs because no embedding generation
  was performed during preparation.
- Knowledge graph: missing in 797,236 candidate pairs because no populated
  Neo4j projection was available.

The resulting values are suitable for review and pipeline validation, not
model training until labels and the required training-time representations
are supplied.

## Label evidence workflow

`label_evidence.csv` is the analyst-review queue. Analysts must provide:

- `positive` only when reliable evidence establishes the same campaign or
  specific threat activity.
- `negative` only when reliable evidence establishes unrelated activity.
- `uncertain` when the relationship cannot be established.
- Evidence citations, reviewer identity, review status, and notes.

No campaign IDs were fabricated. Actor/group names, filenames, URLs, and
report IDs are metadata and must not become model inputs.

## Leakage and limitations

- Do not use report IDs, filenames, URLs, actor IDs, group directory names, or
  campaign-like metadata as features.
- Near-duplicate or syndicated reports can leak source wording between splits;
  group exact duplicates were removed, but a future training split must also
  use content-hash and source-aware grouping.
- Publication dates and source vendor are metadata, not model inputs.
- The corpus is heterogeneous and includes non-technical, educational, and
  general security content.
- Actor-level grouping is not campaign-level ground truth.
- No confirmed positive or negative pair labels were found in the inspected
  repository.

## Conclusion

CTI-EACL24 **does not currently contain enough reliable campaign-level labels
to train CyberMind's intended Random Forest correlation model**. The project is
not training a model and must remain in review/preparation state until
analysts label a sufficiently balanced, evidence-backed set of report pairs.

## Weak supervision status

An automated weak-supervision pass is available in
`backend/training/correlation/weak_supervision.py`. It analyzed all 797,236
candidate pairs without modifying the original pair file. The run produced
2,531 provisional positives, 18,463 provisional negatives, and 776,242
uncertain outcomes. Only 16,785 high-confidence outcomes had complete evidence
and source references and were written to
`backend/data/correlation/processed/silver_correlation_pairs.csv`.

These are machine-generated silver labels, not ground truth. The run found no
independent campaign-level annotations, so label quality has not been
independently established. Of the 19,595 high-confidence rule outcomes, 2,810
lacked complete evidence and 1,399 additional outcomes were medium confidence.
The run recorded 27 conflicting outcomes, 145 distinct campaign references,
and 9 distinct report sources. The eligible silver set contains 2,266
positive and 14,519 negative pairs (approximately 1:6.4), with no duplicate
or synthetic balancing. Training remains blocked; see
`backend/training/correlation/WEAK_SUPERVISION_REPORT.md`.
