# Behavioural Feature Report

## Existing production contract

`behavioural_similarity` remains the existing set-based Jaccard calculation
over normalized behaviour values. It returns a score in `[0, 1]`; if either
report has no comparable behaviour representation it returns neutral `0.5`
with `available=false`. This is the same production missing-data policy used
by the other correlation features.

The previous orchestration path incorrectly supplied only the document
classification category and therefore did not represent described actions or
procedures. It now extracts explicit behaviour evidence from normalized report
text and supplies stable behaviour keys to the same production feature.

## Repaired representation

The deterministic `deterministic_behaviour_lexicon_v1` extractor recognizes
explicit action phrases such as spear-phishing, credential dumping, scheduled
tasks, remote desktop, command-and-control, exfiltration, screenshot capture,
obfuscation, and file encryption. Each emitted key retains its matching source
sentence, character span, and extraction method.

Behaviour keys are category/procedure values such as
`credential_access:credential_dumping`. ATT&CK identifiers are not used as
behaviour values, so ATT&CK technique similarity remains a separate feature.
Actor or malware names alone never emit a behaviour.

No LLM, random value, or synthetic evidence is used.

## Dataset audit

The extractor was run against all 12,095 normalized reports:

| Measure | Count |
|---|---:|
| Reports with explicit behaviour evidence | 4,419 |
| Reports without recognized behaviour evidence | 7,676 |
| Behaviour evidence mentions | 9,149 |
| Report coverage | 36.5358% |

Most frequent explicit values were command-and-control (1,641 reports),
obfuscation (1,340), macros (742), spear-phishing (622), and command-line
execution (608). Reports without an explicit action remain unavailable; they
are not converted to genuine zero similarity.

Applied to the 16,785 eligible silver pairs, the repaired feature currently
has 4,148 missing pairs (24.7125%), 4,396 genuine zero-similarity pairs, and
4,820 neutral-valued pairs. Its mean is 0.26738181 with standard deviation
0.21637964 and range `[0.0, 1.0]`. Positive pairs have mean `0.34550298`;
negative pairs have mean `0.25518933`. These values are also recorded in the
completed v3 metadata and were produced by the same production feature engine
used by inference.

## Validation

Focused tests cover similar procedures, distinct representations, missing
reports, evidence retention, and separation from ATT&CK IDs:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests\test_correlation_features.py -q
```

The production orchestration now uses the same extractor before
`behavioural_similarity`, preserving training/inference preprocessing. The
feature should be recomputed in v3 only after graph ingestion is complete.
