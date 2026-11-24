from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.attack.dataset import AttackDataset, AttackObject
from app.attack.service import map_document
from app.core.config import get_settings
from app.db.models import (
    Campaign,
    CampaignDocumentAssociation,
    CampaignStatus,
    CTIDocument,
    DocumentEntityAssociation,
)
from app.graph.client import Neo4jClient
from app.graph.sync import GraphSynchronizer
from app.vector_store.factory import get_semantic_index

_DEMO_TECHNIQUES: dict[str, tuple[str, str, str]] = {
    "T1053.005": ("Scheduled Task/Job: Scheduled Task", "persistence", "Adversaries may abuse task scheduling functionality to facilitate initial or recurring execution."),
    "T1041": ("Exfiltration Over C2 Channel", "exfiltration", "Adversaries may exfiltrate data over an existing command and control channel."),
    "T1059.001": ("Command and Scripting Interpreter: PowerShell", "execution", "Adversaries may abuse PowerShell commands and scripts for execution."),
    "T1071.001": ("Application Layer Protocol: Web Protocols", "command-and-control", "Adversaries may communicate using application layer protocols such as HTTP and HTTPS."),
    "T1078": ("Valid Accounts", "defense-evasion", "Adversaries may obtain and abuse credentials of existing accounts."),
    "T1105": ("Ingress Tool Transfer", "command-and-control", "Adversaries may transfer tools or other files into a compromised environment."),
    "T1110.003": ("Brute Force: Password Spraying", "credential-access", "Adversaries may use one password against many accounts to acquire valid credentials."),
    "T1190": ("Exploit Public-Facing Application", "initial-access", "Adversaries may exploit weaknesses in internet-facing software."),
    "T1204.002": ("User Execution: Malicious File", "execution", "Adversaries may rely on a user opening a malicious file."),
    "T1486": ("Data Encrypted for Impact", "impact", "Adversaries may encrypt data to interrupt availability."),
    "T1490": ("Inhibit System Recovery", "impact", "Adversaries may impair recovery mechanisms."),
    "T1560.001": ("Archive Collected Data: Archive via Utility", "collection", "Adversaries may archive collected data before exfiltration."),
    "T1566.001": ("Phishing: Spearphishing Attachment", "initial-access", "Adversaries may send spearphishing messages with attachments."),
}


def demo_attack_dataset() -> AttackDataset:
    """Provide an offline subset of canonical ATT&CK IDs used in the demo corpus."""
    objects = {
        external_id: AttackObject(
            external_id=external_id,
            object_type="attack-pattern",
            name=name,
            description=description,
            tactics=(tactic,),
            references=(
                {
                    "source_name": "mitre-attack",
                    "external_id": external_id,
                    "url": f"https://attack.mitre.org/techniques/{external_id.replace('.', '/')}/",
                },
            ),
        )
        for external_id, (name, tactic, description) in _DEMO_TECHNIQUES.items()
    }
    return AttackDataset(version="enterprise-attack-demo-subset-v1", objects=objects)


async def _associate_demo_campaign(
    session: AsyncSession,
    document: CTIDocument,
    payload: dict[str, Any],
) -> None:
    campaign_name = payload.get("campaign_name")
    if not isinstance(campaign_name, str) or not campaign_name.strip():
        return
    campaign_name = campaign_name.strip()
    campaign = await session.scalar(
        select(Campaign).where(Campaign.name == campaign_name).limit(1)
    )
    if campaign is None:
        campaign = Campaign(
            name=campaign_name,
            status=CampaignStatus.CANDIDATE,
            description="Fictional campaign used as demonstration-only source ground truth.",
            confidence=1.0,
            evidence={
                "classification": "synthetic_demo_ground_truth",
                "not_a_model_prediction": True,
            },
        )
        session.add(campaign)
        await session.flush()
    association = await session.scalar(
        select(CampaignDocumentAssociation).where(
            CampaignDocumentAssociation.campaign_id == campaign.id,
            CampaignDocumentAssociation.document_id == document.id,
        )
    )
    if association is None:
        session.add(
            CampaignDocumentAssociation(
                campaign_id=campaign.id,
                document_id=document.id,
                relevance_score=1.0,
                association_reason="Explicit synthetic campaign metadata in fictional demo feed.",
                association_type="demo_ground_truth",
                association_evidence={
                    "classification": "synthetic_demo_ground_truth",
                    "not_a_model_prediction": True,
                    "source_report_id": payload.get("id"),
                },
            )
        )
        await session.flush()


async def process_demo_document(
    session: AsyncSession,
    document: CTIDocument,
    payload: dict[str, Any],
    graph_client: Neo4jClient,
) -> dict[str, int]:
    dataset = demo_attack_dataset()
    mappings, unsupported = await map_document(
        session,
        document,
        dataset,
        explicit_only=True,
    )
    if unsupported:
        raise ValueError(f"Unsupported explicit ATT&CK IDs in demo report: {unsupported}")
    await _associate_demo_campaign(session, document, payload)
    entity_result = await session.execute(
        select(DocumentEntityAssociation)
        .options(selectinload(DocumentEntityAssociation.entity))
        .where(DocumentEntityAssociation.document_id == document.id)
    )
    entity_values = [
        association.entity.normalized_value
        for association in entity_result.scalars().all()
        if association.entity is not None
    ]

    semantic_index = get_semantic_index()
    chunks = await asyncio.to_thread(
        semantic_index.index_document,
        document_id=document.id,
        text=document.normalized_text or document.normalized_content,
        source_id=document.source_id,
        source_url=document.original_url,
        title=document.normalized_title or document.title,
        collected_at=document.retrieved_at,
        published_at=document.published_at,
        document_type=document.document_type,
        entity_values=entity_values,
    )
    graph_result = await GraphSynchronizer(
        graph_client,
        retries=get_settings().neo4j_sync_retries,
    ).sync_document(session, document.id)
    return {
        "attack_mappings": len(mappings),
        "semantic_chunks": chunks,
        "graph_nodes": graph_result.nodes_written,
        "graph_relationships": graph_result.relationships_written,
    }
