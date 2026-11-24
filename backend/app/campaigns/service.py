import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import networkx as nx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.campaigns.naming import (
    CampaignNamingService,
    redact_synthetic_campaign_labels,
)
from app.core.config import get_settings
from app.db.models import (
    Campaign,
    CampaignDocumentAssociation,
    CampaignHistory,
    CampaignStatus,
    CorrelationJob,
    CorrelationJobStatus,
    CorrelationRecord,
    CTIDocument,
    DocumentEntityAssociation,
)
from app.graph.client import Neo4jClient

logger = logging.getLogger(__name__)

NON_TEMPORAL_FEATURES = (
    "entity_relationship_similarity",
    "behavioural_similarity",
    "attack_technique_similarity",
    "knowledge_graph_relationship_similarity",
)


@dataclass(frozen=True)
class StrongCorrelation:
    record: CorrelationRecord
    dimensions: tuple[str, ...]

    @property
    def first_document_id(self) -> UUID:
        return self.record.first_document_id

    @property
    def second_document_id(self) -> UUID:
        return self.record.second_document_id


def _available_dimensions(record: CorrelationRecord, minimum_similarity: float) -> tuple[str, ...]:
    evidence = record.evidence_and_explanation.get("features", {})
    dimensions = []
    for name in NON_TEMPORAL_FEATURES:
        feature = evidence.get(name, {})
        if (
            feature.get("available") is True
            and float(feature.get("score", getattr(record, name))) >= minimum_similarity
        ):
            dimensions.append(name)
    return tuple(dimensions)


def _strong_correlations(
    records: list[CorrelationRecord],
    *,
    probability_threshold: float,
    minimum_similarity: float,
) -> list[StrongCorrelation]:
    strong: list[StrongCorrelation] = []
    for record in records:
        if (
            record.correlation_probability >= probability_threshold
            and record.predicted_relationship_label == "related"
        ):
            dimensions = _available_dimensions(record, minimum_similarity)
            if dimensions:
                strong.append(StrongCorrelation(record, dimensions))
    return strong


def _is_valid_guarded_cluster(
    cluster: set[UUID],
    graph: nx.Graph,
    contradictory_pairs: set[frozenset[UUID]],
    *,
    min_density: float = 0.60,
) -> bool:
    """Evaluate whether a candidate set of documents forms a valid guarded evidence-graph cluster.

    Deterministic criteria:
    1. Size >= 2.
    2. Contradiction Free: No pair of documents in the candidate group has a saved "unrelated" prediction.
    3. Directly Supported Pair (k == 2): Must have an eligible supporting edge between them in graph.
    4. Multi-Report Candidate (k >= 3):
       - Connected: Subgraph induced by the candidate must be connected.
       - Per-Report Support: Every report in the candidate must be supported by >= 2 eligible edges.
       - Edge Density: Edge count / max possible edges >= min_density (default 0.60).
       - Bridge-Free (2-Edge-Connected): No single edge may act as an articulation bridge holding the group together.
    """
    k = len(cluster)
    if k < 2:
        return False

    # 1. Contradiction Check: No pair of reports in cluster may have a saved "unrelated" prediction.
    for u in cluster:
        for v in cluster:
            if u != v and frozenset((u, v)) in contradictory_pairs:
                return False

    subgraph = graph.subgraph(cluster)

    # 2. Size 2: Directly supported pair
    if k == 2:
        u, v = tuple(cluster)
        return subgraph.has_edge(u, v)

    # 3. For size >= 3:
    # Must be connected
    if not nx.is_connected(subgraph):
        return False

    # Per-report support: every report in the candidate must be supported by >= 2 edges
    degrees = dict(subgraph.degree())
    if any(deg < 2 for deg in degrees.values()):
        return False

    # Meaningful edge density (default 0.60 allows 7, 8, 9, 10 edges out of 10 for k=5)
    max_possible_edges = k * (k - 1) // 2
    actual_edges = subgraph.number_of_edges()
    density = actual_edges / max_possible_edges
    if density < min_density:
        return False

    # No weak bridge / cut-edge (2-edge-connected):
    # A single edge must not act as an articulation bridge holding the group together
    if any(True for _ in nx.bridges(subgraph)):
        return False

    return True


def _cluster_edges(
    edges: list[StrongCorrelation],
    records: list[CorrelationRecord] | None = None,
    *,
    min_density: float = 0.60,
) -> list[set[UUID]]:
    """Partition eligible saved edges into campaign candidates using guarded evidence-graph clustering."""
    if not edges:
        return []

    graph = nx.Graph()
    for edge in edges:
        graph.add_edge(
            edge.first_document_id,
            edge.second_document_id,
            weight=edge.record.correlation_probability,
            correlation=edge,
        )

    contradictory_pairs: set[frozenset[UUID]] = set()
    if records:
        for r in records:
            if r.predicted_relationship_label == "unrelated":
                contradictory_pairs.add(frozenset((r.first_document_id, r.second_document_id)))

    # Sort edges descending by probability, tie-break by record ID for determinism
    sorted_edges = sorted(
        edges,
        key=lambda item: (item.record.correlation_probability, str(item.record.id)),
        reverse=True,
    )
    clusters: list[set[UUID]] = []

    for edge in sorted_edges:
        pair = {edge.first_document_id, edge.second_document_id}
        matching = [c for c in clusters if c & pair]
        if not matching:
            clusters.append(pair)
            continue

        union = set().union(*matching, pair)
        if _is_valid_guarded_cluster(union, graph, contradictory_pairs, min_density=min_density):
            clusters = [c for c in clusters if c not in matching] + [union]
        elif not any(pair <= c for c in clusters):
            merged_single = False
            for c in matching:
                cand = c | pair
                if _is_valid_guarded_cluster(cand, graph, contradictory_pairs, min_density=min_density):
                    clusters = [item for item in clusters if item != c] + [cand]
                    merged_single = True
                    break
            if not merged_single:
                clusters.append(pair)

    # Agglomerative merge pass for any clusters that can be combined into a valid guarded cluster
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                union = clusters[i] | clusters[j]
                if _is_valid_guarded_cluster(union, graph, contradictory_pairs, min_density=min_density):
                    clusters = [c for k, c in enumerate(clusters) if k not in (i, j)] + [union]
                    merged = True
                    break
            if merged:
                break

    # Deduplicate subsets (e.g. if a 2-node pair is a proper subset of a larger cluster)
    final_clusters: list[set[UUID]] = []
    for c in clusters:
        if not any(c < other for other in clusters):
            if c not in final_clusters:
                final_clusters.append(c)

    return final_clusters


async def discover_campaigns(
    session: AsyncSession,
    *,
    probability_threshold: float = 0.35,
    minimum_similarity: float = 0.1,
    job_id: UUID | None = None,
    naming_service: CampaignNamingService | None = None,
) -> list[Campaign]:
    latest_job = await session.scalar(
        select(CorrelationJob)
        .where(CorrelationJob.status == CorrelationJobStatus.COMPLETED)
        .order_by(CorrelationJob.completed_at.desc(), CorrelationJob.requested_at.desc())
        .limit(1)
    )
    if latest_job is not None:
        if job_id is not None and job_id != latest_job.id:
            raise ValueError(
                f"The requested correlation job {job_id} is not the latest completed correlation run ({latest_job.id})."
            )
        job_id = latest_job.id
    elif job_id is not None:
        raise ValueError(
            f"The requested correlation job {job_id} is not the latest completed correlation run."
        )

    query = select(CorrelationRecord).order_by(CorrelationRecord.correlation_probability.desc())
    if job_id is not None:
        query = query.where(
            CorrelationRecord.evidence_and_explanation["correlation_job_id"].as_string() == str(job_id)
        )
    result = await session.execute(query)
    records = list(result.scalars().all())
    edges = _strong_correlations(
        records,
        probability_threshold=probability_threshold,
        minimum_similarity=minimum_similarity,
    )
    clusters = _cluster_edges(edges, records)
    if not clusters:
        return []

    graph = nx.Graph()
    for edge in edges:
        graph.add_edge(
            edge.first_document_id,
            edge.second_document_id,
            weight=edge.record.correlation_probability,
            correlation=edge,
        )
    contradictory_pairs: set[frozenset[UUID]] = {
        frozenset((r.first_document_id, r.second_document_id))
        for r in records
        if r.predicted_relationship_label == "unrelated"
    }

    existing_result = await session.execute(
        select(Campaign)
        .options(selectinload(Campaign.document_associations))
    )
    existing_campaigns = list(existing_result.scalars().unique().all())
    synthetic_labels = [
        campaign.name
        for campaign in existing_campaigns
        if campaign.evidence.get("classification") == "synthetic_demo_ground_truth"
    ]
    members_by_campaign = {
        campaign.id: {
            association.document_id for association in campaign.document_associations
        }
        for campaign in existing_campaigns
    }
    discovered: list[Campaign] = []
    naming_service = naming_service or CampaignNamingService()
    for cluster in clusters:
        campaign = _find_extendable_campaign(
            existing_campaigns,
            cluster,
            members_by_campaign,
            graph,
            contradictory_pairs,
            job_id=job_id,
        )
        cluster_edges = [
            edge for edge in edges
            if edge.first_document_id in cluster and edge.second_document_id in cluster
        ]
        confidence = min(
            edge.record.correlation_probability for edge in cluster_edges
        )
        naming_evidence = await _build_naming_evidence(
            session,
            cluster,
            cluster_edges,
            records,
            probability_threshold=probability_threshold,
            synthetic_labels=synthetic_labels,
        )
        supporting_ids = naming_evidence["correlation_ids"]
        discovery_thresholds = {
            "probability_threshold": probability_threshold,
            "minimum_similarity": minimum_similarity,
            "profile": (
                "demonstration_relaxed"
                if probability_threshold < 0.75 or minimum_similarity < 0.5
                else "standard"
            ),
        }
        if job_id is not None:
            discovery_thresholds["correlation_job_id"] = str(job_id)
        evidence = {
            "classification": "correlation_discovered_candidate",
            "discovery_method": "guarded_evidence_graph_v1",
            "relationship_origin": "system_inferred",
            "confidence_basis": "minimum supporting correlation probability",
            "correlation_job_id": str(job_id),
            "discovery_thresholds": discovery_thresholds,
            "supporting_correlation_ids": supporting_ids,
            "supporting_dimensions": naming_evidence["supporting_dimensions"],
            "supporting_report_ids": naming_evidence["report_ids"],
            "source_names": naming_evidence["source_names"],
            "shared_entities": naming_evidence["shared_entities"],
            "pairwise_evidence": naming_evidence["pairwise_correlations"],
            "timeline": naming_evidence["timeline"],
            "member_count": len(cluster),
        }
        if campaign is not None and "last_decision" in campaign.evidence:
            evidence["last_decision"] = campaign.evidence["last_decision"]
        same_evidence = (
            campaign is not None
            and members_by_campaign[campaign.id] == cluster
            and all(
                campaign.evidence.get(key) == value
                for key, value in evidence.items()
            )
        )
        if same_evidence and campaign is not None:
            naming_status = campaign.evidence.get("naming", {}).get("status")
            if naming_status == "ai_generated" or (
                naming_status == "fallback"
                and get_settings().genai_provider == "disabled"
            ):
                discovered.append(campaign)
                continue

        naming = await naming_service.name_campaign(
            naming_evidence,
            synthetic_labels=synthetic_labels,
        )
        evidence["naming"] = {
            **naming.metadata,
            "redacted_synthetic_label_count": len(synthetic_labels),
        }
        now = datetime.now(timezone.utc)
        if campaign is None:
            campaign = Campaign(
                name=naming.name,
                status=CampaignStatus.CANDIDATE,
                description=naming.description,
                confidence=confidence,
                evidence=evidence,
            )
            session.add(campaign)
            await session.flush()
            session.add(
                CampaignHistory(
                    campaign_id=campaign.id,
                    event_type="discovered",
                    new_status=CampaignStatus.CANDIDATE,
                    event_evidence=evidence,
                    occurred_at=now,
                )
            )
            existing_campaigns.append(campaign)
            members_by_campaign[campaign.id] = set()
        else:
            changed = (
                campaign.name != naming.name
                or campaign.description != naming.description
                or campaign.confidence != confidence
                or campaign.evidence != evidence
            )
            campaign.name = naming.name
            campaign.description = naming.description
            campaign.confidence = confidence
            campaign.evidence = evidence
            if changed:
                session.add(
                    CampaignHistory(
                        campaign_id=campaign.id,
                        event_type="updated",
                        previous_status=campaign.status,
                        new_status=campaign.status,
                        event_evidence=evidence,
                        occurred_at=now,
                    )
                )
        existing_ids = members_by_campaign[campaign.id]
        for document_id in sorted(cluster, key=str):
            if document_id in existing_ids:
                continue
            document_edges = [
                edge for edge in cluster_edges
                if document_id in {edge.first_document_id, edge.second_document_id}
            ]
            association_evidence = {
                "relationship_origin": "system_inferred",
                "supporting_correlation_ids": [str(edge.record.id) for edge in document_edges],
                "supporting_dimensions": sorted({
                    dimension for edge in document_edges for dimension in edge.dimensions
                }),
                "confidence": min(
                    edge.record.correlation_probability for edge in document_edges
                ),
            }
            session.add(
                CampaignDocumentAssociation(
                    campaign_id=campaign.id,
                    document_id=document_id,
                    relevance_score=association_evidence["confidence"],
                    association_reason="Guarded evidence-graph correlation within campaign candidate.",
                    association_type="system_inferred",
                    association_evidence=association_evidence,
                )
            )
            existing_ids.add(document_id)
        discovered.append(campaign)
    await session.flush()
    return discovered


def _find_extendable_campaign(
    campaigns: list[Campaign],
    cluster: set[UUID],
    members_by_campaign: dict[UUID, set[UUID]],
    graph: nx.Graph,
    contradictory_pairs: set[frozenset[UUID]],
    *,
    job_id: UUID | None = None,
    min_density: float = 0.60,
) -> Campaign | None:
    for campaign in campaigns:
        if campaign.status == CampaignStatus.REJECTED:
            continue
        if campaign.evidence.get("classification") == "synthetic_demo_ground_truth":
            continue
        if campaign.evidence.get("relationship_origin") != "system_inferred":
            continue
        camp_job_id = campaign.evidence.get("correlation_job_id") or (
            campaign.evidence.get("discovery_thresholds", {}).get("correlation_job_id")
        )
        if job_id is not None and camp_job_id != str(job_id):
            continue
        existing = members_by_campaign.get(campaign.id, set())
        if not existing & cluster:
            continue
        if existing == cluster:
            return campaign
        union = existing | cluster
        if _is_valid_guarded_cluster(union, graph, contradictory_pairs, min_density=min_density):
            return campaign
    return None


async def clear_campaign_candidates(
    session: AsyncSession,
    *,
    job_id: UUID | None = None,
) -> int:
    query = select(Campaign).where(
        Campaign.status == CampaignStatus.CANDIDATE,
    )
    result = await session.execute(query)
    all_candidates = list(result.scalars().all())
    to_delete = []
    for c in all_candidates:
        classification = c.evidence.get("classification")
        if classification == "synthetic_demo_ground_truth":
            continue
        c_job_id = c.evidence.get("correlation_job_id") or (
            c.evidence.get("discovery_thresholds", {}).get("correlation_job_id")
        )
        if job_id is not None and c_job_id != str(job_id):
            continue
        to_delete.append(c)

    deleted_count = len(to_delete)
    if deleted_count > 0:
        delete_ids = [c.id for c in to_delete]
        await session.execute(
            delete(Campaign).where(Campaign.id.in_(delete_ids))
        )
        await session.commit()
        client = None
        try:
            settings = get_settings()
            client = Neo4jClient(
                settings.neo4j_uri,
                settings.neo4j_user,
                settings.neo4j_password,
                settings.neo4j_database,
            )
            with client.session() as neo4j_session:
                for c_id in delete_ids:
                    stable_id = f"Campaign:{c_id}"
                    neo4j_session.run(
                        "MATCH (c:Campaign {stable_id: $stable_id}) DETACH DELETE c",
                        {"stable_id": stable_id},
                    )
        except Exception as exc:
            logger.warning(f"Neo4j campaign candidate cleanup skipped or failed: {exc}")
        finally:
            if client is not None:
                client.close()

    return deleted_count


async def _build_naming_evidence(
    session: AsyncSession,
    cluster: set[UUID],
    cluster_edges: list[StrongCorrelation],
    records: list[CorrelationRecord],
    *,
    probability_threshold: float,
    synthetic_labels: list[str],
) -> dict[str, Any]:
    result = await session.execute(
        select(CTIDocument)
        .options(
            selectinload(CTIDocument.source),
            selectinload(CTIDocument.entity_associations).selectinload(
                DocumentEntityAssociation.entity
            ),
        )
        .where(CTIDocument.id.in_(cluster))
    )
    documents = sorted(result.scalars().unique().all(), key=lambda item: str(item.id))
    documents_by_id = {document.id: document for document in documents}
    if set(documents_by_id) != cluster:
        raise ValueError("A correlated report was not available for campaign naming.")

    report_ids = [str(document.id) for document in documents]
    source_names = sorted({
        document.source.name
        for document in documents
        if document.source is not None
    })
    shared_entities: dict[str, set[str]] = {
        "actors": set(),
        "malware": set(),
        "tools": set(),
        "techniques": set(),
        "indicators": set(),
    }
    evidence_category = {
        "shared_actor": "actors",
        "shared_malware": "malware",
        "shared_tool": "tools",
        "shared_technique": "techniques",
        "shared_indicator": "indicators",
    }
    pairwise_correlations: list[dict[str, Any]] = []
    supporting_ids: set[str] = set()
    supporting_dimensions: set[str] = set()
    for edge in cluster_edges:
        record = edge.record
        record_id = str(record.id)
        supporting_ids.add(record_id)
        supporting_dimensions.update(edge.dimensions)
        record_evidence = record.evidence_and_explanation or {}
        model_evidence = record_evidence.get("model_evidence", {})
        if not isinstance(model_evidence, dict):
            model_evidence = {}
        shared_values = model_evidence.get("shared_values", {})
        if not isinstance(shared_values, dict):
            shared_values = {}
        for key, category in evidence_category.items():
            values = shared_values.get(key, [])
            if isinstance(values, list):
                shared_entities[category].update(
                    str(value) for value in values if isinstance(value, str)
                )
        pairwise_correlations.append({
            "correlation_id": record_id,
            "report_ids": sorted((
                str(record.first_document_id),
                str(record.second_document_id),
            )),
            "probability": record.correlation_probability,
            "label": record.predicted_relationship_label,
            "predictor": record.predictor_type,
            "predictor_version": record.predictor_version,
            "supporting_dimensions": list(edge.dimensions),
            "features": {
                name: {
                    "available": details.get("available"),
                    "score": details.get("score"),
                }
                for name, details in (
                    record_evidence.get("features", {}).items()
                    if isinstance(record_evidence.get("features"), dict)
                    else []
                )
                if isinstance(details, dict) and (details.get("available") or details.get("score", 0) > 0)
            },
            "shared_entities": {
                category: sorted(
                    redact_synthetic_campaign_labels(str(value), synthetic_labels)
                    for value in shared_values.get(key, [])
                    if isinstance(value, str)
                )
                for key, category in evidence_category.items()
            },
        })

    report_entities: dict[UUID, dict[str, set[str]]] = {}
    for document in documents:
        report_entities[document.id] = {
            category: set() for category in shared_entities
        }
        for association in document.entity_associations:
            if association.entity is None:
                continue
            entity_type = str(association.entity.entity_type)
            entity_name = association.entity.canonical_name
            if entity_type in {"threat_actor", "apt_group", "actor"}:
                report_entities[document.id]["actors"].add(entity_name)
            elif entity_type in {"malware", "ransomware"}:
                report_entities[document.id]["malware"].add(entity_name)
            elif entity_type == "tool":
                report_entities[document.id]["tools"].add(entity_name)
            elif entity_type in {"ip_address", "domain", "url", "file_hash", "indicator"}:
                report_entities[document.id]["indicators"].add(entity_name)
    if report_entities:
        for category in shared_entities:
            common_entities = set.intersection(*(
                entities[category] for entities in report_entities.values()
            ))
            shared_entities[category].update(common_entities)

    contradictory_correlations = [
        {
            "correlation_id": str(record.id),
            "report_ids": sorted((
                str(record.first_document_id),
                str(record.second_document_id),
            )),
            "probability": record.correlation_probability,
            "label": record.predicted_relationship_label,
            "predictor": record.predictor_type,
            "predictor_version": record.predictor_version,
        }
        for record in records
        if record.first_document_id in cluster
        and record.second_document_id in cluster
        and str(record.id) not in supporting_ids
        and (
            record.predicted_relationship_label != "related"
            or record.correlation_probability < probability_threshold
        )
    ]
    shared_entities = {
        category: sorted(
            {
                redact_synthetic_campaign_labels(value, synthetic_labels)
                for value in values
            }
            - {
                "[synthetic campaign label withheld]",
                "[synthetic label term withheld]",
            }
        )
        for category, values in shared_entities.items()
    }
    pairwise_correlations.sort(key=lambda item: item["correlation_id"])
    contradictory_correlations.sort(key=lambda item: item["correlation_id"])
    reports = [
        {
            "report_id": str(document.id),
            "title": redact_synthetic_campaign_labels(
                document.original_title or document.title,
                synthetic_labels,
            ),
            "source_name": document.source.name if document.source else "Unknown source",
            "published_at": (
                document.published_at.isoformat()
                if document.published_at
                else None
            ),
            "content_excerpt": redact_synthetic_campaign_labels(
                (document.normalized_content or document.normalized_text or "")[:750],
                synthetic_labels,
            ),
        }
        for document in documents
    ]
    timestamps = [
        document.published_at
        for document in documents
        if document.published_at is not None
    ]
    return {
        "report_ids": report_ids,
        "source_names": source_names,
        "shared_entities": shared_entities,
        "supporting_dimensions": sorted(supporting_dimensions),
        "correlation_ids": sorted(supporting_ids),
        "pairwise_correlations": pairwise_correlations,
        "contradictions": contradictory_correlations,
        "reports": reports,
        "timeline": {
            "start": min(timestamps).isoformat() if timestamps else None,
            "end": max(timestamps).isoformat() if timestamps else None,
        },
    }


async def set_campaign_decision(
    session: AsyncSession,
    campaign: Campaign,
    *,
    status: CampaignStatus,
    comments: str | None = None,
    actor_id: UUID | None = None,
    relationship_origin: str = "analyst_confirmed",
) -> Campaign:
    previous_status = campaign.status
    campaign.status = status
    campaign.evidence = {
        **campaign.evidence,
        "last_decision": {
            "relationship_origin": relationship_origin,
            "comments": comments,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    if status == CampaignStatus.CONFIRMED and relationship_origin == "source_confirmed":
        result = await session.execute(
            select(CampaignDocumentAssociation).where(
                CampaignDocumentAssociation.campaign_id == campaign.id
            )
        )
        for association in result.scalars().all():
            association.association_type = "source_confirmed"
            association.association_evidence = {
                **association.association_evidence,
                "relationship_origin": "source_confirmed",
                "confirmation_comments": comments,
            }
    session.add(
        CampaignHistory(
            campaign_id=campaign.id,
            event_type="analyst_decision",
            previous_status=previous_status,
            new_status=status,
            actor_id=actor_id,
            comments=comments,
            event_evidence={
                "relationship_origin": relationship_origin,
                "analyst_decision": status,
            },
        )
    )
    await session.flush()
    return campaign
