"""Add correlation job lifecycle storage.

Revision ID: 20261116_0006
Revises: 20261116_0005
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0006"
down_revision: Union[str, Sequence[str], None] = "20261116_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "correlation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("rerun", sa.Boolean(), nullable=False),
        sa.Column("pairs_considered", sa.Integer(), nullable=False),
        sa.Column("correlations_created", sa.Integer(), nullable=False),
        sa.Column("predictor_type", sa.String(128), nullable=True),
        sa.Column("predictor_version", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["cti_documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_correlation_jobs_status", "correlation_jobs", ["status"])
    op.create_index("ix_correlation_jobs_document_id", "correlation_jobs", ["document_id"])
    op.create_index("ix_correlation_jobs_campaign_id", "correlation_jobs", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_correlation_jobs_campaign_id", table_name="correlation_jobs")
    op.drop_index("ix_correlation_jobs_document_id", table_name="correlation_jobs")
    op.drop_index("ix_correlation_jobs_status", table_name="correlation_jobs")
    op.drop_table("correlation_jobs")
