from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AssistantConversation, AssistantMessage
from app.core.config import get_settings
from app.genai.base import LLMProviderError, LLMRequest, LLMUnavailableError
from app.genai.factory import create_provider
from app.genai.prompting import SYSTEM_PROMPT, build_assistant_prompt
from app.genai.schemas import InvestigationOutput
from app.rag.service import HybridRetrievalService, RetrievalFilters


class AssistantExecutionError(RuntimeError):
    def __init__(self, message: str, message_id: UUID) -> None:
        super().__init__(message)
        self.message_id = message_id


async def send_assistant_message(
    session: AsyncSession,
    retrieval: HybridRetrievalService,
    conversation: AssistantConversation,
    *,
    content: str,
    campaign_id: UUID | None = None,
    source_id: UUID | None = None,
    document_type: str | None = None,
    entity: str | None = None,
    limit: int = 10,
) -> AssistantMessage:
    user_message = AssistantMessage(
        conversation_id=conversation.id,
        role="user",
        content=content,
        evidence_references=[],
        model_output={},
        provider_metadata={"status": "received"},
    )
    session.add(user_message)
    conversation.updated_at = datetime.now(timezone.utc)
    await session.flush()

    retrieved = await retrieval.retrieve(
        session,
        content,
        filters=RetrievalFilters(
            campaign_id=campaign_id,
            source_id=source_id,
            document_type=document_type,
            entity=entity,
        ),
        limit=limit,
    )
    history_result = await session.execute(
        select(AssistantMessage)
        .where(
            AssistantMessage.conversation_id == conversation.id,
            AssistantMessage.id != user_message.id,
        )
        .order_by(AssistantMessage.created_at.desc())
        .limit(8)
    )
    history = [
        {"role": message.role, "content": message.content}
        for message in reversed(list(history_result.scalars().all()))
    ]

    if not retrieved.evidence:
        output = InvestigationOutput(
            status="insufficient_evidence",
            intelligence_gaps=["No grounded evidence was retrieved for this question."],
        )
        return await _store_response(
            session,
            conversation,
            output,
            retrieved.source_references,
            {"provider": "not_called", "reason": "no_evidence"},
        )

    try:
        try:
            provider = create_provider()
        except LLMUnavailableError:
            if get_settings().genai_provider.casefold() != "disabled":
                raise
            facts = [
                {
                    "text": (
                        f"{item.document_title or 'Retrieved report'}: "
                        f"{item.relevant_text[:700].strip()}"
                    ),
                    "evidence_ids": [item.evidence_id],
                }
                for item in retrieved.evidence[:5]
                if item.relevant_text.strip()
            ]
            if not facts:
                output = InvestigationOutput(
                    status="insufficient_evidence",
                    intelligence_gaps=["Retrieved records did not contain usable report text."],
                )
                return await _store_response(
                    session,
                    conversation,
                    output,
                    retrieved.source_references,
                    {"provider": "not_called", "reason": "empty_retrieved_text"},
                )
            output = InvestigationOutput(
                status="grounded_extractive",
                confirmed_facts=facts,
                intelligence_gaps=[
                    "GenAI is disabled; these are retrieved report excerpts, not a generated synthesis."
                ],
            )
            return await _store_response(
                session,
                conversation,
                output,
                retrieved.source_references,
                {
                    "provider": "offline_extractive",
                    "model": "retrieval-only",
                    "status": "completed",
                    "retrieval_warnings": retrieved.warnings,
                },
            )
        response = await provider.generate(
            LLMRequest(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_assistant_prompt(content, retrieved, history),
                model="",
                temperature=0.0,
            )
        )
        output = InvestigationOutput.model_validate_json(response.content)
        _validate_evidence_ids(output, {item.evidence_id for item in retrieved.evidence})
    except (LLMProviderError, ValidationError, ValueError) as exc:
        failed = AssistantMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="The assistant could not produce a grounded answer.",
            evidence_references=retrieved.source_references,
            model_output={},
            provider_metadata={"status": "failed", "error_type": type(exc).__name__},
            error_message=str(exc),
        )
        session.add(failed)
        await session.flush()
        raise AssistantExecutionError("Grounded assistant request failed", failed.id) from exc

    return await _store_response(
        session,
        conversation,
        output,
        retrieved.source_references,
        {
            "provider": response.provider,
            "model": response.model,
            "response_id": response.response_id,
            "usage": response.usage,
            "retrieval_warnings": retrieved.warnings,
            "status": "completed",
        },
    )


async def _store_response(
    session: AsyncSession,
    conversation: AssistantConversation,
    output: InvestigationOutput,
    evidence_references: list[dict],
    provider_metadata: dict,
) -> AssistantMessage:
    serialized = output.model_dump(mode="json")
    response = AssistantMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=json.dumps(serialized, ensure_ascii=True),
        evidence_references=evidence_references,
        model_output=serialized,
        provider_metadata=provider_metadata,
    )
    session.add(response)
    await session.flush()
    return response


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
            raise ValueError("Assistant output referenced an evidence ID not in retrieved context")
    for event in output.timeline:
        if not set(event.evidence_ids).issubset(evidence_ids):
            raise ValueError("Assistant timeline referenced an evidence ID not in retrieved context")
