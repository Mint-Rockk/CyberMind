import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CTIDocument,
    DocumentEntityAssociation,
    EntityType,
    ExtractedEntity,
)
from app.db.repositories import get_entity_by_value


@dataclass(frozen=True)
class ExtractedMention:
    entity_type: EntityType
    normalized_name: str
    original_text: str
    confidence: float
    evidence_text: str
    start: int
    end: int
    extraction_method: str
    extracted_at: datetime


ALIASES: dict[EntityType, dict[str, str]] = {
    EntityType.THREAT_ACTOR: {
        "apt28": "APT28",
        "fancy bear": "APT28",
        "sofacy": "APT28",
        "apt29": "APT29",
        "cozy bear": "APT29",
        "the dukes": "APT29",
        "lazarus group": "Lazarus Group",
        "hidden cobra": "Lazarus Group",
    },
    EntityType.APT_GROUP: {
        "apt28": "APT28",
        "apt29": "APT29",
        "lazarus group": "Lazarus Group",
        "sandworm": "Sandworm",
        "turla": "Turla",
    },
    EntityType.MALWARE: {
        "emotet": "Emotet",
        "trickbot": "TrickBot",
        "qakbot": "QakBot",
        "cobalt strike": "Cobalt Strike",
        "powershell": "PowerShell",
    },
    EntityType.RANSOMWARE: {
        "lockbit": "LockBit",
        "lockbit 3.0": "LockBit 3.0",
        "blackcat": "ALPHV/BlackCat",
        "alphv": "ALPHV/BlackCat",
        "clop": "Clop",
        "conti": "Conti",
    },
    EntityType.TOOL: {
        "mimikatz": "Mimikatz",
        "cobalt strike": "Cobalt Strike",
        "metasploit": "Metasploit",
        "powershell": "PowerShell",
        "rclone": "Rclone",
    },
    EntityType.SECTOR: {
        "healthcare": "Healthcare",
        "financial services": "Financial Services",
        "government": "Government",
        "energy": "Energy",
        "manufacturing": "Manufacturing",
        "education": "Education",
        "telecommunications": "Telecommunications",
    },
}

_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
_IP_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\d)(?!\.\d)")
_HASH_RE = re.compile(r"(?<![A-Fa-f0-9])(?:[A-Fa-f0-9]{32}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})(?![A-Fa-f0-9])")
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_ATTACK_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"(?<![@\w.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b", re.IGNORECASE)
_CAMPAIGN_RE = re.compile(
    r"\b(?:campaign|operation)\s+(?:named\s+)?([A-Z][A-Za-z0-9_-]{2,50})\b",
    re.IGNORECASE,
)
_VULNERABILITY_RE = re.compile(
    r"\b(?:zero[- ]day|remote code execution|sql injection|buffer overflow|privilege escalation)\b",
    re.IGNORECASE,
)


def _normalise(value: str, entity_type: EntityType) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    if entity_type in {
        EntityType.DOMAIN,
        EntityType.URL,
        EntityType.IP_ADDRESS,
        EntityType.FILE_HASH,
    }:
        return value.rstrip(".,;:)]").lower()
    if entity_type in {EntityType.CVE, EntityType.ATTACK_REFERENCE}:
        return value.upper()
    return value.casefold()


def _evidence(text: str, start: int, end: int) -> str:
    left = text.rfind(".", 0, start) + 1
    right = text.find(".", end)
    return text[left : len(text) if right == -1 else right + 1].strip()


def _mention(
    text: str,
    entity_type: EntityType,
    start: int,
    end: int,
    *,
    confidence: float,
    method: str,
    canonical: str | None = None,
) -> ExtractedMention:
    original = text[start:end]
    return ExtractedMention(
        entity_type=entity_type,
        normalized_name=canonical or _normalise(original, entity_type),
        original_text=original,
        confidence=confidence,
        evidence_text=_evidence(text, start, end),
        start=start,
        end=end,
        extraction_method=method,
        extracted_at=datetime.now(timezone.utc),
    )


def _iter_alias_mentions(text: str) -> Iterable[ExtractedMention]:
    for entity_type, aliases in ALIASES.items():
        for alias, canonical in aliases.items():
            for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", text, re.IGNORECASE):
                yield _mention(
                    text,
                    entity_type,
                    match.start(),
                    match.end(),
                    confidence=0.93,
                    method="alias_dictionary",
                    canonical=canonical,
                )


def _structured_values(value: Any, key: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _structured_values(child_value, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _structured_values(child, key)
    elif isinstance(value, str) and value.strip():
        yield key, value.strip()


def extract_entities(
    text: str,
    structured_metadata: dict[str, Any] | None = None,
) -> list[ExtractedMention]:
    """Extract auditable entities using regexes, aliases, and source metadata."""
    mentions: list[ExtractedMention] = []
    occupied: list[tuple[int, int]] = []

    def add_matches(
        pattern: re.Pattern[str],
        entity_type: EntityType,
        confidence: float,
        method: str,
        *,
        allow_overlap: bool = False,
    ) -> None:
        for match in pattern.finditer(text):
            value = match.group(0).rstrip(".,;:)]")
            end = match.start() + len(value)
            if entity_type == EntityType.IP_ADDRESS:
                try:
                    ipaddress.ip_address(value)
                except ValueError:
                    continue
            if not allow_overlap and any(
                start < end and match.start() < finish for start, finish in occupied
            ):
                continue
            mentions.append(_mention(text, entity_type, match.start(), end, confidence=confidence, method=method))
            occupied.append((match.start(), end))

    add_matches(_URL_RE, EntityType.URL, 0.99, "regex:url")
    add_matches(_HASH_RE, EntityType.FILE_HASH, 0.99, "regex:file_hash")
    add_matches(_CVE_RE, EntityType.CVE, 0.99, "regex:cve")
    add_matches(_ATTACK_RE, EntityType.ATTACK_REFERENCE, 0.98, "regex:attack_reference")
    add_matches(_IP_RE, EntityType.IP_ADDRESS, 0.99, "regex:ip_address", allow_overlap=True)
    add_matches(_DOMAIN_RE, EntityType.DOMAIN, 0.97, "regex:domain", allow_overlap=True)
    add_matches(_VULNERABILITY_RE, EntityType.VULNERABILITY, 0.82, "regex:vulnerability")
    for match in _CAMPAIGN_RE.finditer(text):
        start, end = match.start(1), match.end(1)
        mentions.append(_mention(text, EntityType.CAMPAIGN, start, end, confidence=0.78, method="regex:campaign"))
    mentions.extend(_iter_alias_mentions(text))

    if structured_metadata:
        for key, value in _structured_values(structured_metadata):
            lowered = key.lower()
            entity_type = next(
                (candidate for candidate in EntityType if candidate.value in lowered),
                None,
            )
            if entity_type is None:
                continue
            normalized = _normalise(value, entity_type)
            mentions.append(
                ExtractedMention(
                    entity_type=entity_type,
                    normalized_name=normalized,
                    original_text=value,
                    confidence=0.96,
                    evidence_text=f"structured_metadata[{key}]={value}",
                    start=-1,
                    end=-1,
                    extraction_method="structured_metadata",
                    extracted_at=datetime.now(timezone.utc),
                )
            )

    unique: dict[tuple[EntityType, str], ExtractedMention] = {}
    accepted: list[ExtractedMention] = []
    for mention in sorted(
        mentions, key=lambda item: (item.start < 0, item.start, -(item.end - item.start))
    ):
        if mention.start >= 0 and any(
            existing.entity_type == mention.entity_type
            and existing.start >= 0
            and existing.start < mention.end
            and mention.start < existing.end
            for existing in accepted
        ):
            continue
        accepted.append(mention)
    for mention in accepted:
        unique.setdefault((mention.entity_type, mention.normalized_name), mention)
    return list(unique.values())


async def persist_document_entities(
    session: AsyncSession,
    document: CTIDocument,
    *,
    text: str | None = None,
    structured_metadata: dict[str, Any] | None = None,
) -> list[ExtractedMention]:
    mentions = extract_entities(text or document.normalized_text, structured_metadata)
    for mention in mentions:
        entity = await get_entity_by_value(
            session, mention.entity_type, mention.normalized_name
        )
        if entity is None:
            entity = ExtractedEntity(
                entity_type=mention.entity_type,
                canonical_name=mention.normalized_name,
                normalized_value=mention.normalized_name,
                confidence=mention.confidence,
                attributes={"aliases": [mention.original_text]},
            )
            session.add(entity)
            await session.flush()
        else:
            aliases = entity.attributes.get("aliases", [])
            if mention.original_text not in aliases:
                entity.attributes = {"aliases": [*aliases, mention.original_text]}
        session.add(
            DocumentEntityAssociation(
                document_id=document.id,
                entity_id=entity.id,
                mention_text=mention.original_text,
                evidence_text=mention.evidence_text,
                evidence_start=mention.start if mention.start >= 0 else None,
                evidence_end=mention.end if mention.end >= 0 else None,
                extraction_method=mention.extraction_method,
                confidence=mention.confidence,
                extracted_at=mention.extracted_at,
            )
        )
    await session.flush()
    return mentions
