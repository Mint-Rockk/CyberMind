from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.ml.correlation.base import CorrelationPredictor, PredictorUnavailableError
from app.ml.correlation.baseline_predictor import BaselinePredictor
from app.ml.correlation.model_loader import load_model_artifact, load_model_metadata
from app.ml.correlation.trained_model_adapter import TrainedModelAdapter
from app.ml.correlation.evidence_model import EvidenceAwareRandomForestPredictor


def create_predictor(settings: Settings | None = None) -> CorrelationPredictor:
    settings = settings or get_settings()
    predictor_type = settings.correlation_predictor.casefold()
    if predictor_type == "baseline":
        return BaselinePredictor()
    if predictor_type == "trained_evidence":
        return EvidenceAwareRandomForestPredictor.from_paths(
            Path(settings.correlation_model_artifact),
            Path(settings.correlation_model_metadata),
            Path(settings.correlation_model_metrics),
        )
    if predictor_type != "trained":
        raise ValueError("CORRELATION_PREDICTOR must be baseline, trained, or trained_evidence")
    artifact_path = Path(settings.correlation_model_artifact)
    metadata_path = Path(settings.correlation_model_metadata)
    if not artifact_path.is_file() or not metadata_path.is_file():
        raise PredictorUnavailableError(
            "trained predictor selected but model artifact or metadata is unavailable"
        )
    metadata = load_model_metadata(metadata_path)
    artifact = load_model_artifact(artifact_path)
    return TrainedModelAdapter(artifact, metadata)
