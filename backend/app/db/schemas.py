from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.db.models import (
    CampaignStatus,
    ClassificationCategory,
    CorrelationJobStatus,
    DocumentStatus,
    EntityType,
    IngestionJobStatus,
    InvestigationStatus,
    NormalizationStatus,
    ReviewDecision,
    SourceType,
    UserRole,
)


class SchemaBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    role: UserRole = UserRole.ANALYST


class UserResponse(SchemaBase):
    id: UUID
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class CTISourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    base_url: HttpUrl
    terms_url: HttpUrl | None = None
    reliability_score: float | None = Field(default=None, ge=0, le=1)
    configuration: dict[str, Any] = Field(default_factory=dict)


class CTISourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    source_type: SourceType | None = None
    base_url: HttpUrl | None = None
    terms_url: HttpUrl | None = None
    reliability_score: float | None = Field(default=None, ge=0, le=1)
    is_active: bool | None = None
    configuration: dict[str, Any] | None = None


class CTISourceResponse(SchemaBase):
    id: UUID
    name: str
    source_type: SourceType
    base_url: str
    reliability_score: float | None
    is_active: bool
    terms_url: str | None
    configuration: dict[str, Any]
    health_status: str
    last_successful_collection: datetime | None = None
    reports_collected: int = 0
    created_at: datetime


class IngestionJobCreate(BaseModel):
    source_id: UUID
    status: IngestionJobStatus = IngestionJobStatus.PENDING
    run_now: bool = True


class IngestionJobResponse(SchemaBase):
    id: UUID
    source_id: UUID
    status: IngestionJobStatus
    records_seen: int
    records_created: int
    error_message: str | None
    created_at: datetime


class RawSourceRecordCreate(BaseModel):
    source_id: UUID
    ingestion_job_id: UUID | None = None
    external_id: str = Field(min_length=1, max_length=512)
    content_hash: str = Field(min_length=1, max_length=128)
    source_url: HttpUrl
    retrieved_at: datetime
    payload: dict[str, Any]
    content_type: str | None = Field(default=None, max_length=128)


class RawSourceRecordResponse(SchemaBase):
    id: UUID
    source_id: UUID
    ingestion_job_id: UUID | None
    external_id: str
    content_hash: str
    source_url: str
    retrieved_at: datetime
    payload: dict[str, Any]
    raw_content: str | None
    content_type: str | None
    created_at: datetime


class CTIDocumentCreate(BaseModel):
    source_id: UUID
    raw_record_id: UUID | None = None
    canonical_key: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=1000)
    normalized_content: str
    document_status: DocumentStatus = DocumentStatus.NORMALIZED
    published_at: datetime | None = None
    retrieved_at: datetime
    language: str | None = Field(default=None, max_length=16)
    provenance: dict[str, Any] = Field(default_factory=dict)
    information_confidence: float | None = Field(default=None, ge=0, le=1)


class CTIDocumentResponse(SchemaBase):
    id: UUID
    source_id: UUID
    raw_record_id: UUID | None
    canonical_key: str
    title: str
    normalized_content: str
    original_title: str
    normalized_title: str
    normalized_text: str
    original_url: str
    content_hash: str
    document_type: str
    normalization_status: NormalizationStatus
    duplicate_of_document_id: UUID | None
    duplicate_relationship: str | None
    document_status: DocumentStatus
    published_at: datetime | None
    retrieved_at: datetime
    provenance: dict[str, Any]
    information_confidence: float | None
    classification_category: ClassificationCategory | None
    classification_confidence: float | None
    classification_method: str | None
    classification_evidence: dict[str, Any] | None
    classified_at: datetime | None
    priority_score: float | None
    priority_factors: dict[str, Any] | None
    priority_method: str | None
    prioritized_at: datetime | None
    created_at: datetime


class ExtractedEntityCreate(BaseModel):
    entity_type: EntityType
    canonical_name: str = Field(min_length=1, max_length=512)
    normalized_value: str = Field(min_length=1, max_length=1024)
    confidence: float | None = Field(default=None, ge=0, le=1)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ExtractedEntityResponse(SchemaBase):
    id: UUID
    entity_type: EntityType
    canonical_name: str
    normalized_value: str
    confidence: float | None
    attributes: dict[str, Any]
    created_at: datetime


class DocumentEntityAssociationResponse(SchemaBase):
    id: UUID
    document_id: UUID
    entity_id: UUID
    mention_text: str | None
    evidence_text: str | None
    evidence_start: int | None
    evidence_end: int | None
    extraction_method: str | None
    confidence: float | None
    extracted_at: datetime


class ExtractedEntityDetailResponse(ExtractedEntityResponse):
    document_associations: list[DocumentEntityAssociationResponse] = Field(
        default_factory=list
    )


class ATTACKTechniqueCreate(BaseModel):
    external_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=300)
    object_type: str = Field(default="attack-pattern", max_length=64)
    tactic: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=32)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    external_references: list[dict[str, Any]] = Field(default_factory=list)
    dataset_version: str | None = Field(default=None, max_length=64)


class ATTACKTechniqueResponse(SchemaBase):
    id: UUID
    external_id: str
    name: str
    object_type: str
    tactic: str | None
    version: str | None
    description: str | None
    aliases: list[str]
    external_references: list[dict[str, Any]]
    dataset_version: str | None
    created_at: datetime


class DocumentTechniqueMappingResponse(SchemaBase):
    id: UUID
    document_id: UUID
    technique_id: UUID
    confidence: float | None
    evidence: str | None
    mapping_method: str | None
    mapping_status: str
    dataset_version: str | None


class ATTACKMappingDetailResponse(SchemaBase):
    id: UUID
    document_id: UUID
    technique_id: UUID
    external_id: str
    name: str
    object_type: str
    tactic: str | None
    confidence: float | None
    evidence: str | None
    mapping_method: str | None
    mapping_status: str
    dataset_version: str | None


class ATTACKMappingRunResponse(BaseModel):
    dataset_version: str
    mappings: list[ATTACKMappingDetailResponse]
    unsupported_identifiers: list[str]


class DocumentTechniqueMappingCreate(BaseModel):
    document_id: UUID
    technique_id: UUID
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str | None = None
    mapping_method: str | None = Field(default=None, max_length=128)


class CorrelationRecordCreate(BaseModel):
    first_document_id: UUID
    second_document_id: UUID
    temporal_similarity: float = Field(ge=0, le=1)
    entity_relationship_similarity: float = Field(ge=0, le=1)
    behavioural_similarity: float = Field(ge=0, le=1)
    attack_technique_similarity: float = Field(ge=0, le=1)
    semantic_embedding_similarity: float = Field(ge=0, le=1)
    knowledge_graph_relationship_similarity: float = Field(ge=0, le=1)
    correlation_probability: float = Field(ge=0, le=1)
    prediction_threshold: float = Field(ge=0, le=1)
    predicted_relationship_label: str = Field(min_length=1, max_length=128)
    predictor_type: str = Field(min_length=1, max_length=128)
    predictor_version: str = Field(min_length=1, max_length=64)
    feature_schema_version: str = Field(min_length=1, max_length=64)
    evidence_and_explanation: dict[str, Any]


class CorrelationRecordResponse(SchemaBase):
    id: UUID
    first_document_id: UUID
    second_document_id: UUID
    temporal_similarity: float
    entity_relationship_similarity: float
    behavioural_similarity: float
    attack_technique_similarity: float
    semantic_embedding_similarity: float
    knowledge_graph_relationship_similarity: float
    correlation_probability: float
    prediction_threshold: float
    predicted_relationship_label: str
    predictor_type: str
    predictor_version: str
    feature_schema_version: str
    evidence_and_explanation: dict[str, Any]
    created_at: datetime


class CorrelationJobCreate(BaseModel):
    threshold: float | None = Field(default=None, ge=0, le=1)
    document_id: UUID | None = None
    campaign_id: UUID | None = None
    rerun: bool = False


class CorrelationJobResponse(SchemaBase):
    id: UUID
    status: CorrelationJobStatus
    threshold: float
    document_id: UUID | None
    campaign_id: UUID | None
    rerun: bool
    pairs_considered: int
    correlations_created: int
    predictor_type: str | None
    predictor_version: str | None
    error_message: str | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class CorrelationGraphNode(BaseModel):
    id: str
    type: str  # "report" | "entity"
    label: str
    source_id: str | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    entity_type: str | None = None
    canonical_name: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class CorrelationGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str  # "correlation" | "has_entity"
    label: str
    probability: float | None = None
    prediction_threshold: float | None = None
    is_related: bool | None = None
    predictor_type: str | None = None
    predictor_version: str | None = None
    feature_similarities: dict[str, float] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)


class CorrelationGraphSummary(BaseModel):
    job_id: UUID | None = None
    job_status: str | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    threshold: float | None = None
    pairs_considered: int = 0
    correlations_created: int = 0
    related_count: int = 0
    unrelated_count: int = 0
    report_count: int = 0
    entity_count: int = 0
    predictor_type: str | None = None
    predictor_version: str | None = None


class CorrelationGraphResponse(BaseModel):
    job: CorrelationJobResponse | None = None
    summary: CorrelationGraphSummary
    nodes: list[CorrelationGraphNode] = Field(default_factory=list)
    edges: list[CorrelationGraphEdge] = Field(default_factory=list)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    status: CampaignStatus = CampaignStatus.CANDIDATE
    description: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class CampaignResponse(SchemaBase):
    id: UUID
    name: str
    status: CampaignStatus
    description: str | None
    confidence: float | None
    evidence: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CampaignSourceSummaryResponse(SchemaBase):
    name: str
    base_url: str


class CampaignReportSummaryResponse(SchemaBase):
    id: UUID
    title: str
    original_title: str
    original_url: str
    published_at: datetime | None
    source: CampaignSourceSummaryResponse | None


class CampaignDocumentAssociationResponse(SchemaBase):
    id: UUID
    campaign_id: UUID
    document_id: UUID
    relevance_score: float | None
    association_reason: str | None
    association_type: str
    association_evidence: dict[str, Any]
    document: CampaignReportSummaryResponse | None = None


class CampaignHistoryResponse(SchemaBase):
    id: UUID
    campaign_id: UUID
    event_type: str
    previous_status: str | None
    new_status: str | None
    actor_id: UUID | None
    comments: str | None
    event_evidence: dict[str, Any]
    occurred_at: datetime


class CampaignDetailResponse(CampaignResponse):
    document_associations: list[CampaignDocumentAssociationResponse] = Field(
        default_factory=list
    )
    history: list[CampaignHistoryResponse] = Field(default_factory=list)


class CampaignDiscoveryRequest(BaseModel):
    probability_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    minimum_similarity: float = Field(default=0.1, ge=0.0, le=1.0)
    job_id: UUID | None = Field(default=None, description="Optional correlation job ID to scope candidate discovery")


class CampaignClearResponse(BaseModel):
    status: str
    candidates_cleared: int
    job_id: str | None = None


class CampaignDecisionRequest(BaseModel):
    decision: CampaignStatus
    comments: str | None = None
    actor_id: UUID | None = None
    relationship_origin: str = Field(default="analyst_confirmed", max_length=32)


class GraphSyncResponse(BaseModel):
    resource_id: UUID
    nodes_written: int
    relationships_written: int
    attempts: int


class GraphStatusResponse(BaseModel):
    status: str
    database: str
    detail: str | None = None


class SemanticSearchResultResponse(BaseModel):
    document_id: UUID
    chunk_id: str
    score: float
    text: str
    metadata: dict[str, Any]


class SemanticIndexResponse(BaseModel):
    document_id: UUID
    chunks_indexed: int
    collection: str
    embedding_model: str
    embedding_dimension: int


class RAGRetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=400)
    campaign_id: UUID | None = None
    source_id: UUID | None = None
    published_after: datetime | None = None
    published_before: datetime | None = None
    document_type: str | None = Field(default=None, max_length=64)
    entity: str | None = Field(default=None, max_length=1024)
    minimum_correlation_probability: float = Field(default=0, ge=0, le=1)
    limit: int = Field(default=10, ge=1, le=100)


class EvidenceItemResponse(BaseModel):
    evidence_id: str
    evidence_type: str
    score: float
    document_id: UUID | None
    document_title: str | None
    source_url: str | None
    chunk_id: str | None
    relevant_text: str
    publication_timestamp: datetime | None
    source_reliability: float | None
    provenance: dict[str, Any]


class RAGRetrieveResponse(BaseModel):
    query: str
    evidence: list[EvidenceItemResponse]
    source_references: list[dict[str, Any]]
    context: str
    sufficient_evidence: bool
    warnings: list[str]


class InvestigationCreate(BaseModel):
    campaign_id: UUID | None = None
    assignee_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    status: InvestigationStatus = InvestigationStatus.OPEN
    objective: str | None = None


class InvestigationResponse(SchemaBase):
    id: UUID
    campaign_id: UUID | None
    assignee_id: UUID | None
    title: str
    status: InvestigationStatus
    objective: str | None
    findings: dict[str, Any]
    request_query: str | None
    retrieval_context: str | None
    evidence_references: list[dict[str, Any]]
    model_output: dict[str, Any]
    provider_metadata: dict[str, Any]
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime


class AssistantConversationCreate(BaseModel):
    title: str = Field(default="Threat intelligence assistant", min_length=1, max_length=300)


class AssistantConversationResponse(SchemaBase):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class AssistantMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    campaign_id: UUID | None = None
    source_id: UUID | None = None
    document_type: str | None = Field(default=None, max_length=64)
    entity: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=10, ge=1, le=100)


class AssistantMessageResponse(SchemaBase):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    evidence_references: list[dict[str, Any]]
    model_output: dict[str, Any]
    provider_metadata: dict[str, Any]
    error_message: str | None
    created_at: datetime


class GeneratedReportCreate(BaseModel):
    investigation_id: UUID
    title: str = Field(min_length=1, max_length=300)
    report_type: str = Field(default="technical", pattern="^(executive|technical|campaign)$")
    report_format: str = Field(default="pdf", pattern="^(pdf|markdown)$")


class GeneratedReportRequest(BaseModel):
    investigation_id: UUID
    report_type: str = Field(default="technical", pattern="^(executive|technical|campaign)$")
    report_format: str = Field(default="pdf", pattern="^(pdf|markdown)$")


class GeneratedReportResponse(SchemaBase):
    id: UUID
    investigation_id: UUID
    title: str
    report_format: str
    content: str
    generation_metadata: dict[str, Any]
    created_at: datetime


class AnalystReviewCreate(BaseModel):
    investigation_id: UUID | None = None
    analyst_id: UUID
    target_type: str = Field(min_length=1, max_length=64)
    target_id: UUID
    decision: ReviewDecision = ReviewDecision.PENDING
    comments: str | None = None
    correction: dict[str, Any] | None = None


class AnalystReviewResponse(SchemaBase):
    id: UUID
    investigation_id: UUID | None
    analyst_id: UUID
    target_type: str
    target_id: UUID
    decision: ReviewDecision
    comments: str | None
    correction: dict[str, Any] | None
    evidence_reference: dict[str, Any]
    created_at: datetime


class AuditLogResponse(SchemaBase):
    id: UUID
    actor_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    event_data: dict[str, Any]
    original_value: dict[str, Any] | None
    updated_value: dict[str, Any] | None
    evidence_reference: dict[str, Any]
    decision: str | None
    reason: str | None
    occurred_at: datetime


class AuditLogCreate(BaseModel):
    actor_id: UUID | None = None
    action: str = Field(min_length=1, max_length=128)
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: UUID | None = None
    event_data: dict[str, Any] = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    target_type: str = Field(pattern="^(document|correlation|campaign|investigation)$")
    target_id: UUID
    decision: ReviewDecision
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: dict[str, Any] = Field(default_factory=dict)
    correction: dict[str, Any] | None = None


class ReviewQueueItem(BaseModel):
    target_type: str
    target_id: UUID
    title: str
    status: str
    updated_at: datetime
