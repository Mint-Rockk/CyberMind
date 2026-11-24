import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attack.dataset import (
    AttackDataset,
    AttackObject,
    download_official_dataset,
)
from app.db.models import (
    ATTACKTechnique,
    CTIDocument,
    DocumentEntityAssociation,
    DocumentTechniqueMapping,
    ExtractedEntity,
)

_TECHNIQUE_ID_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE)
_EXPLICIT_METHOD = "explicit_attack_reference"


@dataclass(frozen=True)
class MappingCandidate:
    attack: AttackObject
    confidence: float
    evidence: str
    method: str
    status: str


def _snippet(text: str, start: int, end: int) -> str:
    left = text.rfind(".", 0, start) + 1
    right = text.find(".", end)
    return text[left : len(text) if right == -1 else right + 1].strip()


def find_mapping_candidates(
    text: str,
    dataset: AttackDataset,
    entity_names: list[str] | None = None,
    *,
    explicit_only: bool = False,
) -> tuple[list[MappingCandidate], list[str]]:
    candidates: dict[str, MappingCandidate] = {}
    unsupported: list[str] = []
    for match in _TECHNIQUE_ID_RE.finditer(text):
        external_id = match.group(0).upper()
        attack = dataset.objects.get(external_id)
        if attack is None or attack.object_type != "attack-pattern":
            unsupported.append(external_id)
            continue
        candidates[external_id] = MappingCandidate(
            attack=attack,
            confidence=0.99,
            evidence=f"Explicit ATT&CK reference {external_id}: {_snippet(text, match.start(), match.end())}",
            method=_EXPLICIT_METHOD,
            status="confirmed_reference",
        )

    if not explicit_only:
        lowered = text.casefold()
        for attack in dataset.objects.values():
            if attack.object_type != "attack-pattern":
                continue
            terms = (attack.name, *attack.aliases)
            for term in terms:
                if len(term) < 4:
                    continue
                match = re.search(re.escape(term.casefold()), lowered)
                if match:
                    existing = candidates.get(attack.external_id)
                    candidate = MappingCandidate(
                        attack=attack,
                        confidence=0.82 if term.casefold() == attack.name.casefold() else 0.76,
                        evidence=f"Matched ATT&CK term '{text[match.start():match.end()]}' in: {_snippet(text, match.start(), match.end())}",
                        method="lexical_attack_name",
                        status="inferred",
                    )
                    if existing is None or candidate.confidence > existing.confidence:
                        candidates[attack.external_id] = candidate
                    break

    if entity_names and not explicit_only:
        normalized_entities = {name.casefold() for name in entity_names}
        for source_object in dataset.objects.values():
            source_terms = {source_object.name.casefold(), *(alias.casefold() for alias in source_object.aliases)}
            if not source_terms.intersection(normalized_entities):
                continue
            for target_id in dataset.uses_relationships.get(source_object.external_id, set()):
                target_external_id = next(
                    (
                        object_value.external_id
                        for object_value in dataset.objects.values()
                        if object_value.external_id == target_id
                    ),
                    None,
                )
                attack = dataset.objects.get(target_external_id or "")
                if attack is None or attack.object_type != "attack-pattern":
                    continue
                candidates.setdefault(
                    attack.external_id,
                    MappingCandidate(
                        attack=attack,
                        confidence=0.84,
                        evidence=(
                            f"ATT&CK relationship {source_object.name} uses {attack.external_id}; "
                            "inferred from an extracted entity and not a confirmed use claim."
                        ),
                        method="entity_relationship",
                        status="inferred",
                    ),
                )
    return list(candidates.values()), sorted(set(unsupported))


def _tactic_text(attack: AttackObject) -> str | None:
    return ", ".join(attack.tactics) if attack.tactics else None


async def _get_or_create_technique(
    session: AsyncSession, attack: AttackObject, dataset_version: str
) -> ATTACKTechnique:
    technique = await session.scalar(
        select(ATTACKTechnique).where(ATTACKTechnique.external_id == attack.external_id)
    )
    if technique is None:
        technique = ATTACKTechnique(
            external_id=attack.external_id,
            name=attack.name,
            object_type=attack.object_type,
            tactic=_tactic_text(attack),
            version=attack.version,
            description=attack.description,
            aliases=list(attack.aliases),
            external_references=list(attack.references),
            dataset_version=dataset_version,
        )
        session.add(technique)
        await session.flush()
    return technique


async def map_document(
    session: AsyncSession,
    document: CTIDocument,
    dataset: AttackDataset | None = None,
    *,
    explicit_only: bool = False,
) -> tuple[list[DocumentTechniqueMapping], list[str]]:
    dataset = dataset or await download_official_dataset()
    entities = (
        await session.execute(
            select(ExtractedEntity)
            .join(
                DocumentEntityAssociation,
                DocumentEntityAssociation.entity_id == ExtractedEntity.id,
            )
            .where(DocumentEntityAssociation.document_id == document.id)
        )
    ).scalars().all()
    candidates, unsupported = find_mapping_candidates(
        f"{document.normalized_title} {document.normalized_text}",
        dataset,
        [entity.canonical_name for entity in entities],
        explicit_only=explicit_only,
    )
    mappings: list[DocumentTechniqueMapping] = []
    for candidate in candidates:
        technique = await _get_or_create_technique(
            session, candidate.attack, dataset.version
        )
        mapping = await session.scalar(
            select(DocumentTechniqueMapping).where(
                DocumentTechniqueMapping.document_id == document.id,
                DocumentTechniqueMapping.technique_id == technique.id,
            )
        )
        if mapping is None:
            mapping = DocumentTechniqueMapping(
                document_id=document.id,
                technique_id=technique.id,
                confidence=candidate.confidence,
                evidence=candidate.evidence,
                mapping_method=candidate.method,
                mapping_status=candidate.status,
                dataset_version=dataset.version,
            )
            session.add(mapping)
        elif (mapping.confidence or 0) < candidate.confidence:
            mapping.confidence = candidate.confidence
            mapping.evidence = candidate.evidence
            mapping.mapping_method = candidate.method
            mapping.mapping_status = candidate.status
            mapping.dataset_version = dataset.version
        mappings.append(mapping)
    await session.flush()
    return mappings, unsupported
