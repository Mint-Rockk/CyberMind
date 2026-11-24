from pathlib import Path

import pytest

from app.correlation.feature_schema import FEATURE_NAMES, FeatureVector
from app.ml.correlation.base import PredictorUnavailableError
from app.ml.correlation.evidence_model import (
    EVIDENCE_FEATURE_NAMES,
    MODEL_FEATURE_NAMES,
    EvidenceAwareRandomForestPredictor,
    build_evidence_features,
)


def _vector() -> FeatureVector:
    return FeatureVector(
        values=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
        evidence={name: {"status": "available", "available": True} for name in FEATURE_NAMES},
    )


def _report(report_id: str, vendor: str, text: str, entities: list[dict[str, str]]) -> dict:
    return {
        "report_id": report_id,
        "source_vendor": vendor,
        "normalized_text": text,
        "entities": entities,
    }


def test_evidence_features_match_training_order_and_raw_overlap_policy() -> None:
    first = _report(
        "a",
        "vendor-a",
        "APT28 used 203.0.113.10.",
        [{"type": "threat_actor", "normalized_name": "apt28"}, {"type": "tool", "normalized_name": "tool-x"}],
    )
    second = _report(
        "b",
        "vendor-b",
        "APT28 used 203.0.113.10.",
        [{"type": "threat_actor", "normalized_name": "apt28"}, {"type": "tool", "normalized_name": "tool-x"}],
    )

    values, evidence = build_evidence_features(first, second)

    assert tuple(values) == EVIDENCE_FEATURE_NAMES
    assert values["shared_actor"] == 1.0
    assert values["shared_tool"] == 1.0
    assert values["shared_indicator"] == 1.0
    assert values["cross_vendor"] == 1.0
    assert evidence["method"].endswith("raw_overlap_v1")


class _CaptureModel:
    def __init__(self) -> None:
        self.values = None

    def predict_proba(self, rows):
        self.values = rows[0]
        return [[0.2, 0.8]]


def test_predict_pair_preserves_model_feature_order_and_probability() -> None:
    model = _CaptureModel()
    predictor = EvidenceAwareRandomForestPredictor(
        model,
        {
            "feature_columns": list(MODEL_FEATURE_NAMES),
            "feature_schema_version": "correlation-features-v1",
        },
        threshold=0.35,
    )

    probability, evidence = predictor.predict_pair(
        _vector(),
        _report("a", "vendor-a", "APT28 used 203.0.113.10.", [{"type": "threat_actor", "normalized_name": "apt28"}]),
        _report("b", "vendor-b", "APT28 used 203.0.113.10.", [{"type": "threat_actor", "normalized_name": "apt28"}]),
    )

    assert probability == pytest.approx(0.8)
    assert model.values == (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0)
    assert evidence["model_feature_order"] == list(MODEL_FEATURE_NAMES)


def test_evidence_model_rejects_invalid_artifact_paths(tmp_path: Path) -> None:
    with pytest.raises(PredictorUnavailableError, match="artifact not found"):
        EvidenceAwareRandomForestPredictor.from_paths(
            tmp_path / "missing.joblib",
            tmp_path / "config.json",
            tmp_path / "metrics.json",
        )
