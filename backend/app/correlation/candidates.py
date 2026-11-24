from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class CandidateDocument:
    document_id: UUID
    published_at: datetime | None = None
    entities: frozenset[str] = frozenset()
    attack_techniques: frozenset[str] = frozenset()
    time_window_days: int = 30


@dataclass
class CandidatePair:
    first_document_id: UUID
    second_document_id: UUID
    reasons: set[str] = field(default_factory=set)


def generate_candidate_pairs(
    documents: list[CandidateDocument],
    *,
    semantic_neighbors: dict[UUID, set[UUID]] | None = None,
    graph_neighbors: dict[UUID, set[UUID]] | None = None,
    target_document_ids: set[UUID] | None = None,
) -> list[CandidatePair]:
    """Generate an indexed candidate set without an all-documents cross join."""
    by_pair: dict[tuple[UUID, UUID], CandidatePair] = {}
    known_ids = {document.document_id for document in documents}
    entity_index: dict[str, set[UUID]] = defaultdict(set)
    attack_index: dict[str, set[UUID]] = defaultdict(set)
    time_index: dict[datetime.date, set[UUID]] = defaultdict(set)

    for document in documents:
        for entity in document.entities:
            entity_index[entity.casefold()].add(document.document_id)
        for technique in document.attack_techniques:
            attack_index[technique.casefold()].add(document.document_id)
        if document.published_at:
            date = document.published_at.astimezone(timezone.utc).date()
            for offset in range(-document.time_window_days, document.time_window_days + 1):
                time_index[date + timedelta(days=offset)].add(document.document_id)

    def add(first: UUID, second: UUID, reason: str) -> None:
        if first == second or first not in known_ids or second not in known_ids:
            return
        if target_document_ids is not None and not target_document_ids.intersection(
            {first, second}
        ):
            return
        pair = tuple(sorted((first, second), key=str))
        by_pair.setdefault(pair, CandidatePair(*pair)).reasons.add(reason)

    for index, reason in ((entity_index, "shared_entity"), (attack_index, "shared_attack_technique")):
        for document_ids in index.values():
            ids = sorted(document_ids, key=str)
            if target_document_ids is None:
                for position, first in enumerate(ids):
                    for second in ids[position + 1:]:
                        add(first, second, reason)
            else:
                targets = [document_id for document_id in ids if document_id in target_document_ids]
                for first in targets:
                    for second in ids:
                        add(first, second, reason)

    for document in documents:
        if target_document_ids is not None and document.document_id not in target_document_ids:
            continue
        if not document.published_at:
            continue
        date = document.published_at.astimezone(timezone.utc).date()
        for other in time_index[date]:
            add(document.document_id, other, "compatible_time_window")

    for source, reason in (
        (semantic_neighbors or {}, "semantic_retrieval"),
        (graph_neighbors or {}, "knowledge_graph_relationship"),
    ):
        for first, neighbors in source.items():
            for second in neighbors:
                add(first, second, reason)
    return sorted(by_pair.values(), key=lambda pair: (str(pair.first_document_id), str(pair.second_document_id)))
