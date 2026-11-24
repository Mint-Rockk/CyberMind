import json
from pathlib import Path

import joblib
import pytest

from app.api.v1 import model as model_api
from app.core.config import Settings
from app.correlation.feature_schema import FEATURE_NAMES
from app.ml.correlation.base import PredictorUnavailableError
from app.ml.correlation.baseline_predictor import BaselinePredictor
from app.ml.correlation.evidence_model import EvidenceAwareRandomForestPredictor, MODEL_FEATURE_NAMES
from app.ml.correlation.model_registry import ModelRegistry
from app.ml.correlation.predictor_factory import create_predictor
from app.ml.correlation.trained_model_adapter import TrainedModelAdapter


class InterfaceTestPredictor:
    """Clearly labelled test-only predictor; never a production artifact."""

    def __init__(self, probability: float = 0.8) -> None:
        self.probability = probability

    def predict_proba(self, rows):
        return [[1.0 - self.probability, self.probability] for _ in rows]


def metadata() -> dict:
    return {
        "model_name": "test-only-predictor",
        "model_version": "test-v1",
        "training_date": "2026-11-16",
        "feature_names": list(FEATURE_NAMES),
        "feature_schema_version": "correlation-features-v1",
        "preprocessing_version": "neutral-missing-v1",
        "training_dataset_reference": "test-fixture-only",
        "evaluation_metrics": {"roc_auc": 1.0},
        "artifact_location": "test-fixture.joblib",
    }


def features() -> dict[str, float]:
    return {name: 0.5 for name in FEATURE_NAMES}


def test_baseline_is_weighted_and_explicitly_not_trained() -> None:
    predictor = BaselinePredictor(
        weights={name: index + 1 for index, name in enumerate(FEATURE_NAMES)}
    )

    probability = predictor.predict_probability(features())
    model_metadata = predictor.get_model_metadata()

    assert probability == pytest.approx(0.5)
    assert model_metadata["is_trained_model"] is False
    assert sum(model_metadata["weights"].values()) == pytest.approx(1.0)
    assert predictor.predict_batch([features(), features()]) == pytest.approx([0.5, 0.5])


def test_trained_evidence_is_the_default_predictor() -> None:
    assert Settings(_env_file=None).correlation_predictor == "trained_evidence"
    assert isinstance(
        create_predictor(Settings(_env_file=None, correlation_predictor="baseline")),
        BaselinePredictor,
    )


def test_factory_loads_trained_evidence_model_and_its_input_metadata(tmp_path: Path) -> None:
    artifact_path = tmp_path / "model.joblib"
    config_path = tmp_path / "config.json"
    metrics_path = tmp_path / "metrics.json"
    joblib.dump(InterfaceTestPredictor(), artifact_path)
    config_path.write_text(
        json.dumps({
            "experiment_version": "f1-improvement-v3",
            "feature_schema_version": "correlation-features-v1",
            "base_dataset": "test-fixture-only",
        }),
        encoding="utf-8",
    )
    metrics_path.write_text(
        json.dumps({
            "feature_columns": list(MODEL_FEATURE_NAMES),
            "selected": {
                "family": "random_forest",
                "threshold": 0.35,
                "test": {"f1": 1.0},
            },
        }),
        encoding="utf-8",
    )
    predictor = create_predictor(Settings(
        correlation_predictor="trained_evidence",
        correlation_model_artifact=str(artifact_path),
        correlation_model_metadata=str(config_path),
        correlation_model_metrics=str(metrics_path),
    ))

    assert isinstance(predictor, EvidenceAwareRandomForestPredictor)
    assert predictor.get_model_metadata()["input_count"] == 12
    assert predictor.get_model_metadata()["threshold"] == pytest.approx(0.35)


def test_factory_does_not_fallback_when_trained_evidence_artifact_is_missing(tmp_path: Path) -> None:
    settings = Settings(
        correlation_predictor="trained_evidence",
        correlation_model_artifact=str(tmp_path / "missing.joblib"),
        correlation_model_metadata=str(tmp_path / "missing.json"),
        correlation_model_metrics=str(tmp_path / "missing_metrics.json"),
    )

    with pytest.raises(PredictorUnavailableError, match="artifact not found"):
        create_predictor(settings)


def test_model_status_reports_trained_model_load_failure(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        correlation_predictor="trained_evidence",
        correlation_model_artifact=str(tmp_path / "missing.joblib"),
        correlation_model_metadata=str(tmp_path / "missing.json"),
        correlation_model_metrics=str(tmp_path / "missing_metrics.json"),
    )
    monkeypatch.setattr(model_api, "get_settings", lambda: settings)

    status = model_api.model_status()

    assert status["status"] == "unavailable"
    assert status["configured_predictor"] == "trained_evidence"
    assert status["is_trained_model"] is False
    assert status["error"].endswith("missing.joblib")


def test_evidence_predictor_rejects_artifact_with_wrong_input_count() -> None:
    class SixInputModel(InterfaceTestPredictor):
        n_features_in_ = 6

    with pytest.raises(ValueError, match="expects 6 inputs"):
        EvidenceAwareRandomForestPredictor(
            SixInputModel(),
            {
                "feature_columns": list(MODEL_FEATURE_NAMES),
                "feature_schema_version": "correlation-features-v1",
            },
            threshold=0.35,
        )


def test_trained_adapter_validates_schema_and_probability() -> None:
    predictor = TrainedModelAdapter(InterfaceTestPredictor(), metadata())

    assert predictor.predict_probability(features()) == pytest.approx(0.8)
    assert predictor.predict_batch([features()]) == pytest.approx([0.8])
    assert predictor.get_model_metadata()["is_trained_model"] is True


def test_trained_adapter_rejects_feature_mismatch() -> None:
    invalid = metadata()
    invalid["feature_names"] = list(reversed(FEATURE_NAMES))

    with pytest.raises(ValueError, match="feature names/order"):
        TrainedModelAdapter(InterfaceTestPredictor(), invalid)


def test_trained_adapter_rejects_invalid_probability() -> None:
    invalid_model = InterfaceTestPredictor(probability=1.5)

    with pytest.raises(ValueError, match="outside"):
        TrainedModelAdapter(invalid_model, metadata()).predict_probability(features())


def test_factory_does_not_fallback_when_trained_artifact_is_missing(tmp_path: Path) -> None:
    settings = Settings(
        correlation_predictor="trained",
        correlation_model_artifact=str(tmp_path / "missing.joblib"),
        correlation_model_metadata=str(tmp_path / "missing.json"),
    )

    with pytest.raises(PredictorUnavailableError, match="unavailable"):
        create_predictor(settings)


def test_factory_loads_test_only_artifact_and_metadata(tmp_path: Path) -> None:
    artifact_path = tmp_path / "model.joblib"
    metadata_path = tmp_path / "model_metadata.json"
    joblib.dump(InterfaceTestPredictor(), artifact_path)
    metadata_path.write_text(json.dumps(metadata()), encoding="utf-8")
    settings = Settings(
        correlation_predictor="trained",
        correlation_model_artifact=str(artifact_path),
        correlation_model_metadata=str(metadata_path),
    )

    predictor = create_predictor(settings)

    assert predictor.predict_probability(features()) == pytest.approx(0.8)


def test_factory_rejects_invalid_metadata(tmp_path: Path) -> None:
    artifact_path = tmp_path / "model.joblib"
    metadata_path = tmp_path / "model_metadata.json"
    joblib.dump(InterfaceTestPredictor(), artifact_path)
    metadata_path.write_text(json.dumps({"model_name": "incomplete"}), encoding="utf-8")
    settings = Settings(
        correlation_predictor="trained",
        correlation_model_artifact=str(artifact_path),
        correlation_model_metadata=str(metadata_path),
    )

    with pytest.raises(ValueError, match="metadata is missing"):
        create_predictor(settings)


def test_model_registry_requires_metadata_identity_match(tmp_path: Path) -> None:
    artifact_path = tmp_path / "model.joblib"
    metadata_path = tmp_path / "model_metadata.json"
    joblib.dump(InterfaceTestPredictor(), artifact_path)
    metadata_path.write_text(json.dumps(metadata()), encoding="utf-8")
    registry = ModelRegistry()
    registry.register("different-name", "test-v1", artifact_path, metadata_path)

    with pytest.raises(ValueError, match="identity"):
        registry.load("different-name", "test-v1")
