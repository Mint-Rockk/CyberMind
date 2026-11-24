import json
import pickle
from pathlib import Path
from typing import Any

from app.ml.correlation.base import PredictorUnavailableError


def load_model_artifact(path: Path) -> Any:
    if not path.is_file():
        raise PredictorUnavailableError(f"trained model artifact not found: {path}")
    try:
        import joblib

        return joblib.load(path)
    except (OSError, ImportError, ValueError, EOFError, TypeError, pickle.UnpicklingError) as exc:
        raise PredictorUnavailableError(f"unable to load trained model artifact: {path}") from exc


def load_model_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PredictorUnavailableError(f"trained model metadata not found: {path}")
    try:
        with path.open(encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise PredictorUnavailableError(f"unable to read trained model metadata: {path}") from exc
    if not isinstance(metadata, dict):
        raise PredictorUnavailableError("trained model metadata must be a JSON object")
    return metadata
