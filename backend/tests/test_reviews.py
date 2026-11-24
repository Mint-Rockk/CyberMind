from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    AnalystReview,
    AuditLog,
    Campaign,
    CampaignStatus,
    ReviewDecision,
    User,
    UserRole,
)
from app.review.service import apply_review


@pytest.mark.asyncio
async def test_campaign_review_updates_state_and_appends_audit_history():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        analyst = User(
            email="analyst@example.test",
            display_name="Analyst",
            role=UserRole.ANALYST,
            is_active=True,
        )
        campaign = Campaign(
            name="Candidate",
            status=CampaignStatus.CANDIDATE,
            description="Inferred candidate",
            confidence=0.8,
            evidence={"supporting": ["corr-1"]},
        )
        session.add_all([analyst, campaign])
        await session.flush()
        review = await apply_review(
            session,
            analyst,
            target_type="campaign",
            target_id=campaign.id,
            decision=ReviewDecision.APPROVED,
            reason="Direct evidence supports the candidate.",
            evidence_reference={"evidence_id": "correlation:1"},
            correction=None,
        )
        await session.commit()
        assert review.decision == ReviewDecision.APPROVED
        assert campaign.status == CampaignStatus.CONFIRMED
        logs = (
            await session.execute(select(AuditLog).where(AuditLog.resource_id == campaign.id))
        ).scalars().all()
        assert len(logs) == 1
        assert logs[0].decision == ReviewDecision.APPROVED
        assert logs[0].reason == "Direct evidence supports the candidate."
        assert logs[0].evidence_reference["evidence_id"] == "correlation:1"
        reviews = (await session.execute(select(AnalystReview))).scalars().all()
        assert len(reviews) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_correction_rejects_unapproved_fields():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        analyst = User(
            email="analyst2@example.test",
            display_name="Analyst",
            role=UserRole.ANALYST,
            is_active=True,
        )
        session.add(analyst)
        await session.flush()
        with pytest.raises(ValueError, match="Unsupported correction fields"):
            await apply_review(
                session,
                analyst,
                target_type="document",
                target_id=uuid4(),
                decision=ReviewDecision.CORRECTED,
                reason="Correction test.",
                evidence_reference={},
                correction={"arbitrary_sql": "drop table"},
            )
    await engine.dispose()
