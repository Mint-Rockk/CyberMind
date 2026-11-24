from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ml.correlation.base import PredictorUnavailableError
from app.ml.correlation.model_loader import load_model_artifact, load_model_metadata
from app.ml.correlation.trained_model_adapter import TrainedModelAdapter


@dataclass(frozen=True)
class RegisteredModel:
    name: str
    version: str
    artifact_path: Path
    metadata_path: Path


class ModelRegistry:
    """Explicit registry for externally supplied, versioned model artifacts."""

    def __init__(self) -> None:
        self._models: dict[tuple[str, str], RegisteredModel] = {}

    def register(
        self,
        name: str,
        version: str,
        artifact_path: Path,
        metadata_path: Path,
    ) -> RegisteredModel:
        if not name or not version:
            raise ValueError("registered models require a name and version")
        model = RegisteredModel(name, version, artifact_path, metadata_path)
        self._models[(name, version)] = model
        return model

    def load(self, name: str, version: str) -> TrainedModelAdapter:
        registered = self._models.get((name, version))
        if registered is None:
            raise PredictorUnavailableError(f"model is not registered: {name}:{version}")
        artifact = load_model_artifact(registered.artifact_path)
        metadata = load_model_metadata(registered.metadata_path)
        adapter = TrainedModelAdapter(artifact, metadata)
        if (
            metadata["model_name"] != registered.name
            or metadata["model_version"] != registered.version
        ):
            raise ValueError("registered model identity does not match artifact metadata")
        return adapter

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {"name": model.name, "version": model.version, "artifact_path": str(model.artifact_path)}
            for model in self._models.values()
        ]
