"""Create the initial CyberMind database schema.

Revision ID: 20261116_0001
Revises:
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261116_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def uuid_column() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "users",
        uuid_column(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "cti_sources",
        uuid_column(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("terms_url", sa.String(2048), nullable=True),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("name", name="uq_cti_sources_name"),
    )
    op.create_index("ix_cti_sources_source_type", "cti_sources", ["source_type"], unique=False)

    op.create_table(
        "ingestion_jobs",
        uuid_column(),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("job_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["cti_sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ingestion_jobs_source_id", "ingestion_jobs", ["source_id"], unique=False)
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"], unique=False)

    op.create_table(
        "raw_source_records",
        uuid_column(),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["cti_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingestion_job_id"], ["ingestion_jobs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_raw_source_records_source_external"),
    )
    op.create_index("ix_raw_source_records_source_id", "raw_source_records", ["source_id"], unique=False)
    op.create_index("ix_raw_source_records_ingestion_job_id", "raw_source_records", ["ingestion_job_id"], unique=False)
    op.create_index("ix_raw_source_records_content_hash", "raw_source_records", ["content_hash"], unique=False)

    op.create_table(
        "cti_documents",
        uuid_column(),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("canonical_key", sa.String(512), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("document_status", sa.String(32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("information_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["cti_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_source_records.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("raw_record_id", name="uq_cti_documents_raw_record_id"),
        sa.UniqueConstraint("canonical_key", name="uq_cti_documents_canonical_key"),
    )
    op.create_index("ix_cti_documents_source_id", "cti_documents", ["source_id"], unique=False)
    op.create_index("ix_cti_documents_document_status", "cti_documents", ["document_status"], unique=False)

    op.create_table(
        "extracted_entities",
        uuid_column(),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("canonical_name", sa.String(512), nullable=False),
        sa.Column("normalized_value", sa.String(1024), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("entity_type", "normalized_value", name="uq_extracted_entities_type_value"),
    )
    op.create_index("ix_extracted_entities_entity_type", "extracted_entities", ["entity_type"], unique=False)
    op.create_index("ix_extracted_entities_normalized_value", "extracted_entities", ["normalized_value"], unique=False)

    op.create_table(
        "document_entity_associations",
        uuid_column(),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mention_text", sa.String(1024), nullable=True),
        sa.Column("extraction_method", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["cti_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["extracted_entities.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "entity_id", name="uq_document_entity_associations_pair"),
    )
    op.create_index("ix_document_entity_associations_entity", "document_entity_associations", ["entity_id"], unique=False)

    op.create_table(
        "attack_techniques",
        uuid_column(),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("tactic", sa.String(128), nullable=True),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_attack_techniques_external_id"),
    )
    op.create_index("ix_attack_techniques_tactic", "attack_techniques", ["tactic"], unique=False)

    op.create_table(
        "document_technique_mappings",
        uuid_column(),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technique_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("mapping_method", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["cti_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["technique_id"], ["attack_techniques.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "technique_id", name="uq_document_technique_mapping_pair"),
    )
    op.create_index("ix_document_technique_mappings_technique", "document_technique_mappings", ["technique_id"], unique=False)

    op.create_table(
        "correlation_records",
        uuid_column(),
        sa.Column("first_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("second_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("temporal_similarity", sa.Float(), nullable=False),
        sa.Column("entity_relationship_similarity", sa.Float(), nullable=False),
        sa.Column("behavioural_similarity", sa.Float(), nullable=False),
        sa.Column("attack_technique_similarity", sa.Float(), nullable=False),
        sa.Column("semantic_embedding_similarity", sa.Float(), nullable=False),
        sa.Column("knowledge_graph_relationship_similarity", sa.Float(), nullable=False),
        sa.Column("correlation_probability", sa.Float(), nullable=False),
        sa.Column("prediction_threshold", sa.Float(), nullable=False),
        sa.Column("predicted_relationship_label", sa.String(128), nullable=False),
        sa.Column("predictor_type", sa.String(128), nullable=False),
        sa.Column("predictor_version", sa.String(64), nullable=False),
        sa.Column("feature_schema_version", sa.String(64), nullable=False),
        sa.Column("evidence_and_explanation", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["first_document_id"], ["cti_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["second_document_id"], ["cti_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "first_document_id", "second_document_id", "predictor_version",
            name="uq_correlation_records_document_pair_predictor",
        ),
    )
    op.create_index("ix_correlation_records_probability", "correlation_records", ["correlation_probability"], unique=False)

    op.create_table(
        "campaigns",
        uuid_column(),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"], unique=False)

    op.create_table(
        "campaign_document_associations",
        uuid_column(),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("association_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["cti_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("campaign_id", "document_id", name="uq_campaign_document_associations_pair"),
    )

    op.create_table(
        "investigations",
        uuid_column(),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("findings", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_investigations_campaign_id", "investigations", ["campaign_id"], unique=False)
    op.create_index("ix_investigations_assignee_id", "investigations", ["assignee_id"], unique=False)
    op.create_index("ix_investigations_status", "investigations", ["status"], unique=False)

    op.create_table(
        "generated_reports",
        uuid_column(),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("report_format", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generation_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_generated_reports_investigation_id", "generated_reports", ["investigation_id"], unique=False)

    op.create_table(
        "analyst_reviews",
        uuid_column(),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("analyst_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("correction", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analyst_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_analyst_reviews_investigation_id", "analyst_reviews", ["investigation_id"], unique=False)
    op.create_index("ix_analyst_reviews_analyst_id", "analyst_reviews", ["analyst_id"], unique=False)
    op.create_index("ix_analyst_reviews_decision", "analyst_reviews", ["decision"], unique=False)

    op.create_table(
        "audit_logs",
        uuid_column(),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_data", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"], unique=False)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)


def downgrade() -> None:
    for table in (
        "audit_logs",
        "analyst_reviews",
        "generated_reports",
        "investigations",
        "campaign_document_associations",
        "campaigns",
        "correlation_records",
        "document_technique_mappings",
        "attack_techniques",
        "document_entity_associations",
        "extracted_entities",
        "cti_documents",
        "raw_source_records",
        "ingestion_jobs",
        "cti_sources",
        "users",
    ):
        op.drop_table(table)
