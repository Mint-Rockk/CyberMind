from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.base import get_db_session
from app.db.models import AssistantConversation, AssistantMessage
from app.db.schemas import (
    AssistantConversationCreate,
    AssistantConversationResponse,
    AssistantMessageCreate,
    AssistantMessageResponse,
)
from app.genai.assistant import AssistantExecutionError, send_assistant_message
from app.graph.client import Neo4jClient
from app.graph.service import GraphQueryService
from app.rag.service import HybridRetrievalService
from app.vector_store.factory import get_semantic_index
from app.vector_store.qdrant import SemanticRetrievalService

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _retrieval_service() -> tuple[HybridRetrievalService, Neo4jClient]:
    settings = get_settings()
    graph_client = Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_database,
    )
    return HybridRetrievalService(
        SemanticRetrievalService(get_semantic_index()),
        GraphQueryService(graph_client),
    ), graph_client


@router.post("/conversations", response_model=AssistantConversationResponse, status_code=201)
async def create_conversation(
    request: AssistantConversationCreate,
    session: AsyncSession = Depends(get_db_session),
) -> AssistantConversation:
    conversation = AssistantConversation(title=request.title)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=list[AssistantConversationResponse])
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssistantConversation]:
    result = await session.execute(
        select(AssistantConversation)
        .order_by(AssistantConversation.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[AssistantMessageResponse],
)
async def list_messages(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[AssistantMessage]:
    await _conversation(session, conversation_id)
    result = await session.execute(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation_id)
        .order_by(AssistantMessage.created_at.asc())
    )
    return list(result.scalars().all())


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AssistantMessageResponse,
    status_code=201,
)
async def send_message(
    conversation_id: UUID,
    request: AssistantMessageCreate,
    session: AsyncSession = Depends(get_db_session),
) -> AssistantMessage:
    conversation = await _conversation(session, conversation_id)
    retrieval, graph_client = _retrieval_service()
    try:
        message = await send_assistant_message(
            session,
            retrieval,
            conversation,
            content=request.content,
            campaign_id=request.campaign_id,
            source_id=request.source_id,
            document_type=request.document_type,
            entity=request.entity,
            limit=request.limit,
        )
        await session.commit()
        await session.refresh(message)
        return message
    except AssistantExecutionError as exc:
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail={"message": str(exc), "message_id": str(exc.message_id)},
        ) from exc
    finally:
        graph_client.close()


async def _conversation(
    session: AsyncSession,
    conversation_id: UUID,
) -> AssistantConversation:
    result = await session.execute(
        select(AssistantConversation)
        .options(selectinload(AssistantConversation.messages))
        .where(AssistantConversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Assistant conversation not found")
    return conversation
