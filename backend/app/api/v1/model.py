from fastapi import APIRouter

from app.core.config import get_settings
from app.ml.correlation.base import PredictorUnavailableError
from app.ml.correlation.predictor_factory import create_predictor

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/status")
def model_status() -> dict:
    settings = get_settings()
    try:
        predictor = create_predictor(settings)
        metadata = predictor.get_model_metadata()
        model_features = metadata.get("feature_columns", metadata.get("feature_names", []))
        return {
            "status": "available",
            "configured_predictor": settings.correlation_predictor,
            "is_trained_model": bool(metadata.get("is_trained_model", False)),
            "model_name": metadata.get("model_name"),
            "input_count": len(model_features),
            "metadata": metadata,
            "feature_schema_version": metadata.get("feature_schema_version"),
            "threshold": float(metadata.get("threshold", settings.correlation_threshold)),
        }
    except PredictorUnavailableError as exc:
        return {
            "status": "unavailable",
            "configured_predictor": settings.correlation_predictor,
            "is_trained_model": False,
            "model_name": None,
            "input_count": None,
            "metadata": {},
            "feature_schema_version": None,
            "threshold": settings.correlation_threshold,
            "error": str(exc),
        }
