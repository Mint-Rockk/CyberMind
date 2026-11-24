from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class UserRole(StrEnum):
    ANALYST = "analyst"
    ADMIN = "admin"


class SourceType(StrEnum):
    RSS = "rss"
    ADVISORY = "advisory"
    NVD = "nvd"
    MITRE_ATTACK = "mitre_attack"
    TAXII = "taxii"
    OSINT = "osint"
    RESEARCH = "research"


class IngestionJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CorrelationJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentStatus(StrEnum):
    INGESTED = "ingested"
    NORMALIZED = "normalized"
    REVIEWED = "reviewed"


class NormalizationStatus(StrEnum):
    PENDING = "pending"
    NORMALIZED = "normalized"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class EntityType(StrEnum):
    THREAT_ACTOR = "threat_actor"
    APT_GROUP = "apt_group"
    MALWARE = "malware"
    RANSOMWARE = "ransomware"
    TOOL = "tool"
    IP_ADDRESS = "ip_address"
    DOMAIN = "domain"
    URL = "url"
    FILE_HASH = "file_hash"
    CVE = "cve"
    VULNERABILITY = "vulnerability"
    CAMPAIGN = "campaign"
    SECTOR = "sector"
    ATTACK_REFERENCE = "attack_reference"
    ACTOR = "actor"
    INDICATOR = "indicator"
    ORGANIZATION = "organization"
    LOCATION = "location"


class ClassificationCategory(StrEnum):
    RANSOMWARE = "ransomware"
    PHISHING = "phishing"
    MALWARE = "malware"
    VULNERABILITY_EXPLOITATION = "vulnerability_exploitation"
    DATA_BREACH = "data_breach"
    CREDENTIAL_THEFT = "credential_theft"
    APT_ACTIVITY = "apt_activity"
    BOTNET = "botnet"
    SUPPLY_CHAIN_ATTACK = "supply_chain_attack"
    OTHER = "other"


class CampaignStatus(StrEnum):
    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class InvestigationStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class ReviewDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTED = "corrected"


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(String(32), default=UserRole.ANALYST)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    investigations: Mapped[list["Investigation"]] = relationship(back_populates="assignee")
    reviews: Mapped[list["AnalystReview"]] = relationship(back_populates="analyst")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="actor")


class CTISource(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "cti_sources"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    source_type: Mapped[SourceType] = mapped_column(String(32), index=True)
    base_url: Mapped[str] = mapped_column(String(2048))
    reliability_score: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    terms_url: Mapped[str | None] = mapped_column(String(2048))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(back_populates="source")
    raw_records: Mapped[list["RawSourceRecord"]] = relationship(back_populates="source")
    documents: Mapped[list["CTIDocument"]] = relationship(back_populates="source")


class IngestionJob(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"

    source_id: Mapped[UUID] = mapped_column(ForeignKey("cti_sources.id", ondelete="CASCADE"), index=True)
    status: Mapped[IngestionJobStatus] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    job_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    source: Mapped["CTISource"] = relationship(back_populates="ingestion_jobs")
    raw_records: Mapped[list["RawSourceRecord"]] = relationship(back_populates="ingestion_job")


class RawSourceRecord(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "raw_source_records"

    source_id: Mapped[UUID] = mapped_column(ForeignKey("cti_sources.id", ondelete="CASCADE"), index=True)
    ingestion_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(String(2048))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_source_records_source_external"),
        Index("ix_raw_source_records_content_hash", "content_hash"),
    )

    source: Mapped["CTISource"] = relationship(back_populates="raw_records")
    ingestion_job: Mapped["IngestionJob | None"] = relationship(back_populates="raw_records")
    document: Mapped["CTIDocument | None"] = relationship(back_populates="raw_record", uselist=False)


class CTIDocument(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "cti_documents"

    source_id: Mapped[UUID] = mapped_column(ForeignKey("cti_sources.id", ondelete="RESTRICT"), index=True)
    raw_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raw_source_records.id", ondelete="SET NULL"), unique=True
    )
    canonical_key: Mapped[str] = mapped_column(String(512), unique=True)
    title: Mapped[str] = mapped_column(String(1000))
    normalized_content: Mapped[str] = mapped_column(Text)
    original_title: Mapped[str] = mapped_column(String(1000), default="")
    normalized_title: Mapped[str] = mapped_column(String(1000), default="")
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    original_url: Mapped[str] = mapped_column(String(2048), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    document_type: Mapped[str] = mapped_column(
        String(64), default="unknown", index=True
    )
    normalization_status: Mapped[NormalizationStatus] = mapped_column(
        String(32), default=NormalizationStatus.NORMALIZED, index=True
    )
    duplicate_of_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cti_documents.id", ondelete="SET NULL"), index=True
    )
    duplicate_relationship: Mapped[str | None] = mapped_column(String(32))
    document_status: Mapped[DocumentStatus] = mapped_column(String(32), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    information_confidence: Mapped[float | None] = mapped_column(Float)
    classification_category: Mapped[ClassificationCategory | None] = mapped_column(
        String(64), index=True
    )
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    classification_method: Mapped[str | None] = mapped_column(String(128))
    classification_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority_score: Mapped[float | None] = mapped_column(Float, index=True)
    priority_factors: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    priority_method: Mapped[str | None] = mapped_column(String(128))
    prioritized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped["CTISource"] = relationship(back_populates="documents")
    raw_record: Mapped["RawSourceRecord | None"] = relationship(back_populates="document")
    duplicate_of: Mapped["CTIDocument | None"] = relationship(
        remote_side="CTIDocument.id",
        foreign_keys=[duplicate_of_document_id],
        back_populates="duplicates",
    )
    duplicates: Mapped[list["CTIDocument"]] = relationship(
        foreign_keys=[duplicate_of_document_id],
        back_populates="duplicate_of",
    )
    entity_associations: Mapped[list["DocumentEntityAssociation"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    technique_mappings: Mapped[list["DocumentTechniqueMapping"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    campaign_associations: Mapped[list["CampaignDocumentAssociation"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    correlations_as_first: Mapped[list["CorrelationRecord"]] = relationship(
        foreign_keys="CorrelationRecord.first_document_id", back_populates="first_document"
    )
    correlations_as_second: Mapped[list["CorrelationRecord"]] = relationship(
        foreign_keys="CorrelationRecord.second_document_id", back_populates="second_document"
    )


class ExtractedEntity(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "extracted_entities"

    entity_type: Mapped[EntityType] = mapped_column(String(32), index=True)
    canonical_name: Mapped[str] = mapped_column(String(512))
    normalized_value: Mapped[str] = mapped_column(String(1024))
    confidence: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    document_associations: Mapped[list["DocumentEntityAssociation"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "normalized_value", name="uq_extracted_entities_type_value"),
        Index("ix_extracted_entities_normalized_value", "normalized_value"),
    )


class DocumentEntityAssociation(UUIDMixin, Base):
    __tablename__ = "document_entity_associations"

    document_id: Mapped[UUID] = mapped_column(ForeignKey("cti_documents.id", ondelete="CASCADE"))
    entity_id: Mapped[UUID] = mapped_column(ForeignKey("extracted_entities.id", ondelete="CASCADE"))
    mention_text: Mapped[str | None] = mapped_column(String(1024))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    evidence_start: Mapped[int | None] = mapped_column(Integer)
    evidence_end: Mapped[int | None] = mapped_column(Integer)
    extraction_method: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float | None] = mapped_column(Float)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("document_id", "entity_id", name="uq_document_entity_associations_pair"),
        Index("ix_document_entity_associations_entity", "entity_id"),
    )

    document: Mapped["CTIDocument"] = relationship(back_populates="entity_associations")
    entity: Mapped["ExtractedEntity"] = relationship(back_populates="document_associations")


class ATTACKTechnique(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "attack_techniques"

    external_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    object_type: Mapped[str] = mapped_column(String(64), default="attack-pattern", index=True)
    tactic: Mapped[str | None] = mapped_column(String(128), index=True)
    version: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    external_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    dataset_version: Mapped[str | None] = mapped_column(String(64), index=True)

    document_mappings: Mapped[list["DocumentTechniqueMapping"]] = relationship(
        back_populates="technique", cascade="all, delete-orphan"
    )


class DocumentTechniqueMapping(UUIDMixin, Base):
    __tablename__ = "document_technique_mappings"

    document_id: Mapped[UUID] = mapped_column(ForeignKey("cti_documents.id", ondelete="CASCADE"))
    technique_id: Mapped[UUID] = mapped_column(ForeignKey("attack_techniques.id", ondelete="CASCADE"))
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[str | None] = mapped_column(Text)
    mapping_method: Mapped[str | None] = mapped_column(String(128))
    mapping_status: Mapped[str] = mapped_column(String(32), default="inferred")
    dataset_version: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("document_id", "technique_id", name="uq_document_technique_mapping_pair"),
        Index("ix_document_technique_mappings_technique", "technique_id"),
    )

    document: Mapped["CTIDocument"] = relationship(back_populates="technique_mappings")
    technique: Mapped["ATTACKTechnique"] = relationship(back_populates="document_mappings")


class CorrelationRecord(UUIDMixin, Base):
    __tablename__ = "correlation_records"

    first_document_id: Mapped[UUID] = mapped_column(ForeignKey("cti_documents.id", ondelete="CASCADE"))
    second_document_id: Mapped[UUID] = mapped_column(ForeignKey("cti_documents.id", ondelete="CASCADE"))
    temporal_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    entity_relationship_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    behavioural_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    attack_technique_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    semantic_embedding_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    knowledge_graph_relationship_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    correlation_probability: Mapped[float] = mapped_column(Float, nullable=False)
    prediction_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_relationship_label: Mapped[str] = mapped_column(String(128), nullable=False)
    predictor_type: Mapped[str] = mapped_column(String(128), nullable=False)
    predictor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_and_explanation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("first_document_id", "second_document_id", "predictor_version",
                         name="uq_correlation_records_document_pair_predictor"),
        Index("ix_correlation_records_probability", "correlation_probability"),
    )

    first_document: Mapped["CTIDocument"] = relationship(
        foreign_keys=[first_document_id], back_populates="correlations_as_first"
    )
    second_document: Mapped["CTIDocument"] = relationship(
        foreign_keys=[second_document_id], back_populates="correlations_as_second"
    )


class CorrelationJob(UUIDMixin, Base):
    __tablename__ = "correlation_jobs"

    status: Mapped[CorrelationJobStatus] = mapped_column(String(32), index=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cti_documents.id", ondelete="SET NULL"), index=True
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    rerun: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pairs_considered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correlations_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    predictor_type: Mapped[str | None] = mapped_column(String(128))
    predictor_version: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Campaign(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(300))
    status: Mapped[CampaignStatus] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    document_associations: Mapped[list["CampaignDocumentAssociation"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    history: Mapped[list["CampaignHistory"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    investigations: Mapped[list["Investigation"]] = relationship(back_populates="campaign")


class CampaignDocumentAssociation(UUIDMixin, Base):
    __tablename__ = "campaign_document_associations"

    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("cti_documents.id", ondelete="CASCADE"))
    relevance_score: Mapped[float | None] = mapped_column(Float)
    association_reason: Mapped[str | None] = mapped_column(Text)
    association_type: Mapped[str] = mapped_column(String(32), default="system_inferred")
    association_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "document_id", name="uq_campaign_document_associations_pair"),
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="document_associations")
    document: Mapped["CTIDocument"] = relationship(back_populates="campaign_associations")


class CampaignHistory(UUIDMixin, Base):
    __tablename__ = "campaign_history"

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str | None] = mapped_column(String(32))
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    comments: Mapped[str | None] = mapped_column(Text)
    event_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="history")


class GraphSyncState(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "graph_sync_states"

    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", name="uq_graph_sync_states_resource"),
    )


class Investigation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "investigations"

    campaign_id: Mapped[UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    assignee_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[InvestigationStatus] = mapped_column(String(32), index=True)
    objective: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    request_query: Mapped[str | None] = mapped_column(Text)
    retrieval_context: Mapped[str | None] = mapped_column(Text)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    model_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    campaign: Mapped["Campaign | None"] = relationship(back_populates="investigations")
    assignee: Mapped["User | None"] = relationship(back_populates="investigations")
    reports: Mapped[list["GeneratedReport"]] = relationship(back_populates="investigation")
    reviews: Mapped[list["AnalystReview"]] = relationship(back_populates="investigation")


class AssistantConversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "assistant_conversations"

    title: Mapped[str] = mapped_column(String(300))
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    messages: Mapped[list["AssistantMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.created_at",
    )


class AssistantMessage(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "assistant_messages"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    model_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    conversation: Mapped["AssistantConversation"] = relationship(back_populates="messages")


class GeneratedReport(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "generated_reports"

    investigation_id: Mapped[UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    report_format: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    content_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    generation_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    investigation: Mapped["Investigation"] = relationship(back_populates="reports")


class AnalystReview(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "analyst_reviews"

    investigation_id: Mapped[UUID | None] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    analyst_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[UUID] = mapped_column()
    decision: Mapped[ReviewDecision] = mapped_column(String(32), index=True)
    comments: Mapped[str | None] = mapped_column(Text)
    correction: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_reference: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    investigation: Mapped["Investigation | None"] = relationship(back_populates="reviews")
    analyst: Mapped["User"] = relationship(back_populates="reviews")


class AuditLog(UUIDMixin, Base):
    __tablename__ = "audit_logs"

    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID | None] = mapped_column()
    event_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    original_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_reference: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    decision: Mapped[str | None] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor: Mapped["User | None"] = relationship(back_populates="audit_logs")
