# CTI-EACL24 Dataset Inventory

## Inspection result

The dataset was inspected in place under `backend/data/CTI-EACL24`. Original
files were not renamed, modified, deleted, or downloaded again.

The repository identifies itself as the dataset for the EACL 2024 paper
"Threat Behavior Textual Search by Attention Graph Isomorphism". Its README
describes:

- A large-scale textual corpus collected from eight vendors.
- Threat reports organized by APT group.
- A manually verified evaluation set containing URLs to reports.
- Additional Malpedia and ThaiCERT collections.

## Files and formats

| Area | Observed format | Use |
|---|---|---|
| `threat-reports-large/*/data/` | Plain-text report files; Kaspersky has `.txt` files whose CSV names omit the extension | Vendor corpus |
| `threat-reports-large/*/data_list.csv` | Headerless six-column CSV: title, date, author, tags, URL, filename | Vendor metadata |
| `threat-reports-per-group/extra/malpedia/*/` | Plain-text files | Actor/group-organized reports |
| `threat-reports-per-group/extra/thaicert/*/` | Plain-text files | Actor/group-organized reports |
| `threat-reports-per-group/our-eval-set/*.txt` | One URL per line | Evaluation URL index, not local report text |
| Root and subdirectory README files | Markdown | Dataset documentation and licensing notice |

The preparation discovery found **15,735 local report files** after excluding
the 12 evaluation URL-list files and documentation/CSV metadata files. The
vendor CSV fallback for Kaspersky filenames was handled reproducibly.

## Available metadata

- Vendor/source: available for the large vendor corpus and Malpedia/ThaiCERT
  collection type.
- Title, publication date, author, tags, and source URL: available where the
  vendor CSV supplies them.
- Actor/group organization: available from Malpedia/ThaiCERT directory names
  and evaluation-list filenames.
- Report text: available for local report files.
- URLs, CVEs, indicators, malware/tool names, campaign-like phrases, and
  explicit ATT&CK identifiers: extracted only when present in text or source
  metadata.
- Campaign identifiers: **not supplied as reliable campaign/incident labels**.

The APT-group directory names are retained as actor/group metadata only. They
are not used as campaign ground truth because the same actor can conduct
multiple campaigns and different actors can participate in related activity.

## Preparation counts

The reproducible preparation run produced:

- 15,735 discovered local report files.
- 12,095 unique, non-empty normalized reports.
- 598 empty reports excluded.
- 3,042 exact normalized-content duplicates excluded.
- 11,910 reports with usable publication dates.
- 8,427 reports with at least one extracted entity.
- 81 reports with explicit ATT&CK technique references.

The exact machine-readable counts are in
`backend/data/correlation/processed/dataset_metadata.json`.

## Licensing and use restrictions

The dataset README says that copyrights belong to the original authors or
vendors, requests citation of the EACL 2024 paper, and prohibits misuse of
attack information. No permissive dataset license was identified in the
inspected files. Any model training or redistribution must therefore be
reviewed against the dataset README, original vendor terms, attribution
requirements, and applicable law.

## Limitations

The dataset is suitable for CTI text processing and actor/group retrieval
experiments, but the inspected files do not establish positive or negative
report-pair campaign labels. The evaluation URL lists also do not contain the
linked report text locally. Campaign-level supervised training is therefore
blocked until analysts review candidate relationships using
`label_evidence.csv`.
