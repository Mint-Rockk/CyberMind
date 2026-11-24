from datetime import datetime, timezone

from app.correlation.feature_schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from app.db.models import EntityType
from app.extraction.service import ExtractedMention
from training.correlation.prepare_dataset import (
    PreparedReport,
    build_uncertain_pairs,
    decode_report,
    parse_date,
    prepare_reports,
)


def _report(report_id: str, text: str, published_at: datetime | None) -> PreparedReport:
    mention = ExtractedMention(
        entity_type=EntityType.CVE,
        normalized_name="CVE-2024-1234",
        original_text="CVE-2024-1234",
        confidence=0.99,
        evidence_text=text,
        start=0,
        end=13,
        extraction_method="test",
        extracted_at=datetime.now(timezone.utc),
    )
    return PreparedReport(
        report_id=report_id,
        original_filename=f"{report_id}.txt",
        relative_path=f"data/{report_id}.txt",
        original_text=text,
        normalized_text=text,
        title=report_id,
        published_at=published_at,
        source_vendor="test",
        source_url=None,
        actor_group=None,
        author=None,
        tags=(),
        encoding="utf-8",
        content_hash=report_id,
        entities=[mention],
        attack_techniques=(),
        referenced_urls=(),
    )


def test_decode_and_date_normalization():
    text, encoding = decode_report("Threat report".encode("utf-8"))
    assert text == "Threat report"
    assert encoding == "utf-8"
    assert parse_date("2024-01-02").isoformat() == "2024-01-02T00:00:00+00:00"


def test_duplicate_detection_and_metadata_extraction(tmp_path):
    root = tmp_path / "dataset"
    data = root / "threat-reports-large" / "vendor" / "data"
    data.mkdir(parents=True)
    (root / "threat-reports-large" / "vendor" / "data_list.csv").write_text(
        "Title, 2024-01-02, Author, CVE, https://example.test/a, one.txt\n"
        "Copy, 2024-01-03, Author, CVE, https://example.test/b, two.txt\n",
        encoding="utf-8",
    )
    (data / "one.txt").write_text("<p>CVE-2024-1234</p>", encoding="utf-8")
    (data / "two.txt").write_text("CVE-2024-1234", encoding="utf-8")
    reports, inventory = prepare_reports(root)
    assert len(reports) == 1
    assert inventory["exact_duplicates"] == 1
    assert reports[0].published_at is not None
    assert reports[0].entities[0].normalized_name == "CVE-2024-1234"


def test_pair_generation_is_uncertain_and_schema_bounded():
    first = _report("a", "CVE-2024-1234", datetime(2024, 1, 1, tzinfo=timezone.utc))
    second = _report("b", "CVE-2024-1234", datetime(2024, 1, 2, tzinfo=timezone.utc))
    pairs = build_uncertain_pairs([first, second])
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["label"] == "uncertain"
    assert pair["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert all(0.0 <= pair[name] <= 1.0 for name in (
        "temporal_similarity",
        "entity_relationship_similarity",
        "behavioural_similarity",
        "attack_technique_similarity",
        "semantic_similarity",
        "knowledge_graph_similarity",
    ))
    assert len(FEATURE_NAMES) == 6


def test_label_domain_excludes_unreviewed_values():
    assert {"positive", "negative", "uncertain"} == {
        "positive", "negative", "uncertain"
    }
