from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Investigation, InvestigationStatus
from app.genai.base import LLMProviderError, LLMRequest
from app.genai.factory import create_provider
from app.genai.prompting import SYSTEM_PROMPT, build_investigation_prompt
from app.genai.schemas import InvestigationOutput
from app.rag.service import HybridRetrievalService, RetrievalFilters


class InvestigationExecutionError(RuntimeError):
    def __init__(self, message: str, investigation_id: UUID) -> None:
        super().__init__(message)
        self.investigation_id = investigation_id


async def run_investigation(
    session: AsyncSession,
    retrieval: HybridRetrievalService,
    *,
    query: str,
    campaign_id: UUID | None = None,
    source_id: UUID | None = None,
    document_type: str | None = None,
    entity: str | None = None,
    limit: int = 10,
) -> Investigation:
    retrieved = await retrieval.retrieve(
        session,
        query,
        filters=RetrievalFilters(
            campaign_id=campaign_id,
            source_id=source_id,
            document_type=document_type,
            entity=entity,
        ),
        limit=limit,
    )
    investigation = Investigation(
        campaign_id=campaign_id,
        title=f"Threat investigation: {query[:270]}",
        status=InvestigationStatus.IN_PROGRESS,
        objective=query,
        request_query=query,
        retrieval_context=retrieved.context,
        evidence_references=retrieved.source_references,
        findings={},
        model_output={},
        provider_metadata={"retrieval_warnings": retrieved.warnings},
    )
    session.add(investigation)
    await session.flush()

    if not retrieved.evidence:
        output = InvestigationOutput(
            status="insufficient_evidence",
            intelligence_gaps=["No grounded evidence was retrieved for this query."],
        )
        _complete(investigation, output, {"provider": "not_called", "reason": "no_evidence"})
        await session.flush()
        return investigation

    try:
        provider = create_provider()
        response = await provider.generate(
            LLMRequest(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_investigation_prompt(query, retrieved),
                model="",
                temperature=0.0,
            )
        )
        output = InvestigationOutput.model_validate_json(response.content)
        _validate_evidence_ids(output, {item.evidence_id for item in retrieved.evidence})
    except (LLMProviderError, ValidationError, ValueError) as exc:
        investigation.status = InvestigationStatus.OPEN
        investigation.error_message = str(exc)
        investigation.completed_at = datetime.now(timezone.utc)
        investigation.provider_metadata = {
            **investigation.provider_metadata,
            "status": "failed",
            "error_type": type(exc).__name__,
        }
        await session.flush()
        raise InvestigationExecutionError("Grounded investigation failed", investigation.id) from exc

    _complete(
        investigation,
        output,
        {
            "provider": response.provider,
            "model": response.model,
            "response_id": response.response_id,
            "usage": response.usage,
            "status": "completed",
        },
    )
    await session.flush()
    return investigation


def _validate_evidence_ids(output: InvestigationOutput, evidence_ids: set[str]) -> None:
    for statement in (
        *output.confirmed_facts,
        *output.inferred_relationships,
        *output.model_interpretations,
        *output.recommendations,
        *output.campaign_explanation,
        *output.relationship_explanation,
        *output.actor_analysis,
        *output.malware_analysis,
        *output.vulnerability_analysis,
        *output.attack_technique_analysis,
        *output.sector_analysis,
    ):
        if not set(statement.evidence_ids).issubset(evidence_ids):
            raise ValueError("LLM output referenced an evidence ID not in retrieved context")
    for event in output.timeline:
        if not set(event.evidence_ids).issubset(evidence_ids):
            raise ValueError("LLM timeline referenced an evidence ID not in retrieved context")


def _complete(
    investigation: Investigation,
    output: InvestigationOutput,
    provider_metadata: dict,
) -> None:
    investigation.status = InvestigationStatus.CLOSED
    serialized_output = output.model_dump(mode="json")
    investigation.findings = serialized_output
    investigation.model_output = serialized_output
    investigation.provider_metadata = {
        **investigation.provider_metadata,
        **provider_metadata,
    }
    investigation.completed_at = datetime.now(timezone.utc)
