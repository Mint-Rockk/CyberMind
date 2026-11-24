from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FeatureResult:
    """A normalized feature plus explicit availability and reproducible evidence."""

    feature_name: str
    score: float
    available: bool
    evidence: dict[str, Any]

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("feature scores must be between 0 and 1")
        if not self.evidence.get("status"):
            raise ValueError("feature evidence must include a status")


@dataclass(frozen=True)
class DocumentRepresentation:
    """Dependency-light representation accepted by all feature services."""

    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    activity_start: datetime | None = None
    activity_end: datetime | None = None
    entities: tuple[str, ...] = ()
    behaviours: tuple[str, ...] = ()
    attack_techniques: tuple[str, ...] = ()
    embedding: tuple[float, ...] | None = None
    knowledge_graph_relationships: tuple[tuple[str, str, str], ...] = ()
    metadata: dict[str, Any] | None = None
