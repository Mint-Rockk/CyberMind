from collections.abc import Mapping, Sequence
from typing import Any

from app.correlation.types import DocumentRepresentation


def value(document: Any, name: str, default: Any = None) -> Any:
    if isinstance(document, Mapping):
        return document.get(name, default)
    return getattr(document, name, default)


def representation(document: Any) -> DocumentRepresentation:
    if isinstance(document, DocumentRepresentation):
        return document
    metadata = value(document, "metadata", None)
    return DocumentRepresentation(
        published_at=value(document, "published_at"),
        retrieved_at=value(document, "retrieved_at"),
        activity_start=value(document, "activity_start"),
        activity_end=value(document, "activity_end"),
        entities=tuple(normalize_values(value(document, "entities", ()))),
        behaviours=tuple(normalize_values(value(document, "behaviours", ()))),
        attack_techniques=tuple(normalize_values(value(document, "attack_techniques", ()))),
        embedding=tuple(value(document, "embedding")) if value(document, "embedding") is not None else None,
        knowledge_graph_relationships=tuple(
            normalize_relationships(value(document, "knowledge_graph_relationships", ()))
        ),
        metadata=metadata,
    )


def normalize_values(values: Any) -> list[str]:
    if values is None or isinstance(values, (str, bytes)):
        values = [values] if values else []
    if not isinstance(values, Sequence):
        return []
    normalized: list[str] = []
    for item in values:
        if isinstance(item, Mapping):
            item = item.get("normalized_value") or item.get("canonical_name") or item.get("name")
        if item is not None and str(item).strip():
            normalized.append(str(item).strip().casefold())
    return sorted(set(normalized))


def normalize_relationships(values: Any) -> list[tuple[str, str, str]]:
    if values is None or isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        return []
    relationships: list[tuple[str, str, str]] = []
    for item in values:
        if isinstance(item, Mapping):
            source = item.get("source") or item.get("subject")
            relation = item.get("relation") or item.get("predicate")
            target = item.get("target") or item.get("object")
            item = (source, relation, target)
        if isinstance(item, Sequence) and len(item) == 3 and all(item):
            relationships.append(tuple(str(part).strip().casefold() for part in item))
    return sorted(set(relationships))


def set_similarity(first: Sequence[Any], second: Sequence[Any]) -> tuple[float | None, dict[str, Any]]:
    def canonical(item: Any) -> Any:
        if isinstance(item, str):
            return item.strip().casefold()
        if isinstance(item, tuple):
            return tuple(canonical(part) for part in item)
        return item

    left, right = {canonical(item) for item in first}, {canonical(item) for item in second}
    if not left or not right:
        return None, {"status": "missing", "reason": "both representations need a non-empty comparable set"}
    intersection = sorted(left & right)
    union = left | right
    return len(intersection) / len(union), {
        "status": "observed",
        "shared": intersection,
        "left_count": len(left),
        "right_count": len(right),
    }
