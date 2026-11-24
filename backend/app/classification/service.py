import re
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CTIDocument,
    CTISource,
    ClassificationCategory,
    DocumentEntityAssociation,
    EntityType,
    ExtractedEntity,
)

CLASSIFICATION_METHOD = "rule_based_v1"
PRIORITY_METHOD = "weighted_factors_v1"

KEYWORDS: dict[ClassificationCategory, tuple[str, ...]] = {
    ClassificationCategory.RANSOMWARE: (
        "ransomware", "ransom", "encrypt files", "double extortion", "lockbit",
        "blackcat", "alphv", "clop", "conti",
    ),
    ClassificationCategory.PHISHING: (
        "phishing", "spearphishing", "credential harvesting", "malicious email",
        "fake login", "business email compromise",
    ),
    ClassificationCategory.MALWARE: (
        "malware", "trojan", "backdoor", "loader", "emotet", "trickbot",
        "qakbot", "malicious payload",
    ),
    ClassificationCategory.VULNERABILITY_EXPLOITATION: (
        "exploit", "exploitation", "zero-day", "vulnerability", "cve-",
        "remote code execution", "privilege escalation",
    ),
    ClassificationCategory.DATA_BREACH: (
        "data breach", "breach", "exfiltrat", "stolen data", "leaked data",
        "records exposed", "unauthorized access",
    ),
    ClassificationCategory.CREDENTIAL_THEFT: (
        "credential theft", "credential stealing", "password theft", "steal credentials",
        "infostealer", "keylogger", "token theft",
    ),
    ClassificationCategory.APT_ACTIVITY: (
        "apt", "advanced persistent threat", "state-sponsored", "nation-state",
        "apt28", "apt29", "lazarus group", "sandworm",
    ),
    ClassificationCategory.BOTNET: (
        "botnet", "command and control", "c2 infrastructure", "zombie network",
        "mirai",
    ),
    ClassificationCategory.SUPPLY_CHAIN_ATTACK: (
        "supply chain", "dependency confusion", "malicious package", "compromised vendor",
        "third-party provider",
    ),
}

SEVERITY_WEIGHTS: dict[ClassificationCategory, float] = {
    ClassificationCategory.RANSOMWARE: 0.95,
    ClassificationCategory.APT_ACTIVITY: 0.90,
    ClassificationCategory.VULNERABILITY_EXPLOITATION: 0.88,
    ClassificationCategory.SUPPLY_CHAIN_ATTACK: 0.86,
    ClassificationCategory.DATA_BREACH: 0.82,
    ClassificationCategory.CREDENTIAL_THEFT: 0.72,
    ClassificationCategory.BOTNET: 0.70,
    ClassificationCategory.MALWARE: 0.68,
    ClassificationCategory.PHISHING: 0.62,
    ClassificationCategory.OTHER: 0.35,
}


@dataclass(frozen=True)
class ClassificationResult:
    category: ClassificationCategory
    confidence: float
    evidence: dict[str, Any]
    method: str = CLASSIFICATION_METHOD


def classify_text(text: str) -> ClassificationResult:
    lowered = text.casefold()
    scores: dict[ClassificationCategory, int] = {}
    evidence: dict[ClassificationCategory, list[str]] = {}
    for category, keywords in KEYWORDS.items():
        matches = [
            keyword for keyword in keywords
            if re.search(re.escape(keyword), lowered)
        ]
        scores[category] = len(matches)
        evidence[category] = matches
    category = max(scores, key=scores.get)
    if scores[category] == 0:
        return ClassificationResult(
            category=ClassificationCategory.OTHER,
            confidence=0.25,
            evidence={"supporting_keywords": [], "matched_count": 0},
        )
    confidence = min(0.98, 0.52 + scores[category] * 0.10)
    return ClassificationResult(
        category=category,
        confidence=round(confidence, 3),
        evidence={
            "supporting_keywords": evidence[category],
            "matched_count": scores[category],
            "category_scores": {key.value: value for key, value in scores.items()},
        },
    )


def classify_document(document: CTIDocument) -> ClassificationResult:
    return classify_text(f"{document.normalized_title} {document.normalized_text}")


def apply_classification(document: CTIDocument, result: ClassificationResult) -> None:
    document.classification_category = result.category
    document.classification_confidence = result.confidence
    document.classification_method = result.method
    document.classification_evidence = result.evidence
    document.classified_at = datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def prioritize_document(
    session: AsyncSession,
    document: CTIDocument,
) -> dict[str, Any]:
    if document.classification_category is None:
        apply_classification(document, classify_document(document))
    category = ClassificationCategory(document.classification_category)
    source = await session.get(CTISource, document.source_id)
    source_reliability = source.reliability_score if source and source.reliability_score is not None else 0.5
    information_confidence = (
        document.information_confidence
        if document.information_confidence is not None
        else 0.5
    )
    corroborating_sources = await session.scalar(
        select(func.count(distinct(CTIDocument.source_id)))
        .where(
            CTIDocument.content_hash == document.content_hash,
            CTIDocument.id != document.id,
        )
    )
    corroborating_sources = int(corroborating_sources or 0)
    independent_corroboration = min(1.0, corroborating_sources / 2)
    campaign_count = await session.scalar(
        select(func.count(DocumentEntityAssociation.id))
        .join(
            ExtractedEntity,
            ExtractedEntity.id == DocumentEntityAssociation.entity_id,
        )
        .where(
            DocumentEntityAssociation.document_id == document.id,
            ExtractedEntity.entity_type == EntityType.CAMPAIGN.value,
        )
    )
    campaign_relevance = 1.0 if campaign_count else 0.0
    reference_time = _utc(document.published_at or document.retrieved_at)
    age_days = max(0.0, (datetime.now(timezone.utc) - reference_time).total_seconds() / 86400)
    recency = round(max(0.0, min(1.0, exp(-age_days / 30))), 4)
    factors = {
        "threat_severity": SEVERITY_WEIGHTS[category],
        "recency": recency,
        "source_reliability": source_reliability,
        "information_confidence": information_confidence,
        "independent_corroboration": independent_corroboration,
        "campaign_relevance": campaign_relevance,
        "corroborating_source_count": corroborating_sources,
        "weights": {
            "threat_severity": 0.30,
            "recency": 0.15,
            "source_reliability": 0.15,
            "information_confidence": 0.15,
            "independent_corroboration": 0.15,
            "campaign_relevance": 0.10,
        },
        "fallbacks": {
            "source_reliability": source is None or source.reliability_score is None,
            "information_confidence": document.information_confidence is None,
        },
    }
    score = sum(factors[name] * factors["weights"][name] for name in factors["weights"])
    document.priority_score = round(score, 4)
    document.priority_factors = factors
    document.priority_method = PRIORITY_METHOD
    document.prioritized_at = datetime.now(timezone.utc)
    return factors
