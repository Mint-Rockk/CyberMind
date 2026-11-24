# Campaign/Incident Group Reconstruction Report

## Conclusion

A leakage-safe campaign/incident grouping for all of
`correlation-dataset-v3` cannot currently be constructed from the available
evidence. Training must remain blocked until campaign or incident assignments
are independently reviewed or supplied by a trusted source.

No pair IDs, labels, six-feature values, original reports, or derived datasets
were modified.

## Sources inspected

- `backend/data/correlation/processed/report_metadata.csv`
- `backend/data/correlation/processed/normalized_reports.jsonl`
- `backend/data/correlation/processed/label_evidence.csv`
- `backend/data/correlation/processed/v3/silver_correlation_pairs.csv`
- `backend/data/correlation/weak_supervision/silver_labels.csv`
- `backend/data/correlation/weak_supervision/labelling_evidence.csv`
- Live Neo4j Community `5.26.5` projection and relationship properties
- `weak_supervision.py` campaign/incident evidence rules

The report metadata has no campaign, incident, or operation identifier column.
It contains source/vendor, actor-group metadata, titles, URLs, dates, and
content hashes. Actor-group values occur for 1,782 reports, but actor groups
are not campaign identifiers and were not used as groups.

The analyst-review evidence file has 797,236 rows, and every
`campaign_or_incident_group` value is blank. The weak-supervision evidence
does retain a `campaign_reference` for some P1 positive rules, but that value
is a text extraction, not a canonical identifier or verified annotation.

## Neo4j assessment

Neo4j is reachable and contains:

| Evidence | Count |
|---|---:|
| `ThreatReport` nodes | 12,095 |
| Reports with provenance | 12,095 |
| `Campaign` nodes | 1,039 |
| Reports with `MENTIONS` edges to campaigns | 2,153 |
| Report-to-campaign `MENTIONS` relationships | 4,759 |

These relationships are not safe campaign groups. The graph projection
currently represents extracted entity mentions, not verified report-to-
campaign assertions. Sample campaign nodes include generic values such as
`using`, `that`, `can`, `called`, and `has`; their relationship evidence is
sentence-level extraction text. No direct, provenance-backed campaign
relationship type was established for grouping. Shared graph entities
therefore remain evidence for correlation, not group identity.

## Tested grouping strategy

The conservative candidate strategy was:

1. Use only high-confidence positive P1 links where both reports explicitly
   mention the same extracted campaign/operation name.
2. Do not use shared actor, malware, tool, technique, source, filename, URL,
   or graph entity as a group identifier.
3. Keep P2 links (two distinctive indicators plus incident context within
   90 days) as correlation evidence only because they have no named incident
   identifier.
4. Build connected components only as a diagnostic; do not treat components
   as accepted groups unless every bridge is independently compatible and no
   explicit negative evidence conflicts.

This strategy is evidence-preserving and reproducible, but the diagnostic
test rejects its transitive components as training groups.

## Reconstruction results

| Measure | Result |
|---|---:|
| v3 eligible pairs | 16,785 |
| v3 pair reports | 814 |
| High-confidence positive pairs | 2,266 |
| P1 named-campaign positive pairs | 2,247 |
| P1 links with a nonblank campaign reference | 2,247 |
| Distinct extracted P1 names | 129 |
| P1-linked reports | 783 |
| P1 connected components | 81 |
| P1-linked reports in multi-name components | 304 |
| Explicit negative silver pairs inside P1 components | 616 |
| P2 positive pairs without named group IDs | 24 |
| v3 pair reports covered by P1 components | 554 |
| v3 pair reports unresolved by P1 components | 260 |
| v3 pairs with both endpoints P1-covered | 6,942 |
| v3 pairs with at least one unresolved endpoint | 9,843 |

The largest P1 component contains 259 reports and bridges many different
campaign-reference strings, including `blockbuster`, `buhtrap`, `ghostsecret`,
`lotus`, `shadowhammer`, `troy`, `turla`, and `xor`. This is transitive
over-merging, not evidence that all 259 reports describe one incident.

The stricter P3 variant, requiring the same named reference across different
source vendors, still produces 728 links in 54 components, 272 reports in
multi-reference components, and 502 explicit negative pairs inside those
components. Independent-source corroboration improves confidence in a direct
link but does not make arbitrary transitive closure safe.

## Conflicts and unresolved evidence

The silver rule distribution contains 2,247 P1 links, 24 P2 links, and
2,266 positive pairs overall; 1,483 positive pairs also receive P3
independent-source corroboration. P2 links have no canonical campaign or
incident name and were not converted to group assignments.

The P1 component test finds 616 negative pairs inside the proposed components:
598 use N1, 17 use N1+N2, and 1 uses N1+N3. These conflicts make the
components unsuitable for leakage grouping without manual resolution.

All unresolved pairs remain unresolved rather than receiving singleton,
source-derived, actor-derived, or fabricated group IDs. Assigning every
unresolved report to a unique synthetic group would also be unsafe for this
pair dataset because reports shared across pairs could still appear across
partitions without a validated incident boundary.

## Split feasibility

A leakage-safe 70:15:15 campaign/incident-grouped split is **not feasible**:

- authoritative campaign/incident IDs are absent from source metadata;
- Neo4j campaign mentions are noisy extracted entities, not verified group
  relationships;
- P1 text references cover only part of the pair-report population;
- P1 transitive closure creates explicit label conflicts and over-merging;
- P2 evidence does not provide stable incident IDs; and
- independent campaign annotations are unavailable.

The defensible next step is to obtain reviewer-confirmed campaign/incident
groups, ideally with source citations and a rule for syndicated reports and
content-hash families. Until then, retain the existing silver labels and
features unchanged, keep unresolved pairs out of grouped training
experiments, and do not claim that a random or source-grouped split is
campaign leakage-safe.

## Reproducibility

The audit used the existing weak-supervision output and live Neo4j queries.
The key checks were:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m training.correlation.recompute_v3
.\.venv\Scripts\python.exe -m pytest tests\test_correlation_features.py tests\test_graph.py -q
```

The grouping analysis itself was read-only. No model training was run.
