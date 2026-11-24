from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class SentenceEmbeddingService:
    """Lazy wrapper around one configured pretrained Sentence Transformer."""

    def __init__(
        self,
        model_name: str,
        *,
        model_version: str,
        expected_dimension: int,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self.expected_dimension = expected_dimension
        self.batch_size = batch_size
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            dimension = self._model.get_embedding_dimension()
            if dimension != self.expected_dimension:
                raise ValueError(
                    f"Embedding model dimension {dimension} does not match configured "
                    f"dimension {self.expected_dimension}"
                )
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def metadata(self) -> dict[str, str | int]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "dimension": self.expected_dimension,
            "preprocessing_version": "whitespace-normalized-v1",
        }
