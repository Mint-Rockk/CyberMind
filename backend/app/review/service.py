from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.service import set_campaign_decision
from app.db.models import (
    AnalystReview,
    AuditLog,
    Campaign,
    CampaignStatus,
    CorrelationRecord,
    CTIDocument,
    Investigation,
    ReviewDecision,
    User,
)

TARGET_TYPES = {"document", "correlation", "campaign", "investigation"}
CORRECTION_FIELDS = {
    "classification_category",
    "information_confidence",
    "priority_score",
    "priority_factors",
}


async def apply_review(
    session: AsyncSession,
    analyst: User,
    *,
    target_type: str,
    target_id: UUID,
    decision: ReviewDecision,
    reason: str,
    evidence_reference: dict[str, Any],
    correction: dict[str, Any] | None,
) -> AnalystReview:
    if target_type not in TARGET_TYPES:
        raise ValueError("Unsupported review target")
    if correction:
        if target_type != "document":
            raise ValueError("Corrections are currently supported for document assessments only")
        unknown = set(correction) - CORRECTION_FIELDS
        if unknown:
            raise ValueError(f"Unsupported correction fields: {sorted(unknown)}")
    target = await _target(session, target_type, target_id)
    original = _original_value(target_type, target)
    updated = dict(original)

    if correction:
        for field, value in correction.items():
            setattr(target, field, value)
        updated = _original_value(target_type, target)

    if target_type == "campaign":
        if decision not in {ReviewDecision.APPROVED, ReviewDecision.REJECTED}:
            raise ValueError("Campaign review must approve or reject the candidate")
        await set_campaign_decision(
            session,
            target,
            status=(
                CampaignStatus.CONFIRMED
                if decision == ReviewDecision.APPROVED
                else CampaignStatus.REJECTED
            ),
            comments=reason,
            actor_id=analyst.id,
            relationship_origin="analyst_confirmed",
        )
        updated = _original_value(target_type, target)

    review = AnalystReview(
        investigation_id=target_id if target_type == "investigation" else None,
        analyst_id=analyst.id,
        target_type=target_type,
        target_id=target_id,
        decision=decision,
        comments=reason,
        correction=correction,
        evidence_reference=evidence_reference,
    )
    session.add(review)
    await session.flush()
    session.add(
        AuditLog(
            actor_id=analyst.id,
            action="review_decision",
            resource_type=target_type,
            resource_id=target_id,
            event_data={
                "append_only": True,
                "review_id": str(review.id),
                "analyst_note": reason,
            },
            original_value=original,
            updated_value=updated,
            evidence_reference=evidence_reference,
            decision=decision,
            reason=reason,
        )
    )
    await session.flush()
    return review


async def _target(session: AsyncSession, target_type: str, target_id: UUID) -> Any:
    target_class = {
        "document": CTIDocument,
        "correlation": CorrelationRecord,
        "campaign": Campaign,
        "investigation": Investigation,
    }[target_type]
    target = await session.get(target_class, target_id)
    if target is None:
        raise LookupError(f"{target_type.title()} target not found")
    return target


def _original_value(target_type: str, target: Any) -> dict[str, Any]:
    if target_type == "document":
        return {
            "classification_category": target.classification_category,
            "information_confidence": target.information_confidence,
            "priority_score": target.priority_score,
            "priority_factors": target.priority_factors,
        }
    if target_type == "correlation":
        return {
            "predicted_relationship_label": target.predicted_relationship_label,
            "correlation_probability": target.correlation_probability,
            "predictor_type": target.predictor_type,
            "predictor_version": target.predictor_version,
        }
    if target_type == "campaign":
        return {"status": _value(target.status), "confidence": target.confidence}
    return {"status": _value(target.status), "findings": target.findings}


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value
