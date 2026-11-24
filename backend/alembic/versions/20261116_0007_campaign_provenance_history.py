"""Add campaign association provenance and lifecycle history.

Revision ID: 20261116_0007
Revises: 20261116_0006
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0007"
down_revision: Union[str, Sequence[str], None] = "20261116_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaign_document_associations",
        sa.Column("association_type", sa.String(32), nullable=True),
    )
    op.add_column(
        "campaign_document_associations",
        sa.Column("association_evidence", sa.JSON(), nullable=True),
    )
    op.execute(
        """
        UPDATE campaign_document_associations
        SET association_type = 'system_inferred',
            association_evidence = '{}'
        """
    )
    op.alter_column("campaign_document_associations", "association_type", nullable=False)
    op.alter_column("campaign_document_associations", "association_evidence", nullable=False)
    op.create_table(
        "campaign_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("new_status", sa.String(32), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("event_evidence", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaign_history_campaign_id", "campaign_history", ["campaign_id"])
    op.create_index("ix_campaign_history_event_type", "campaign_history", ["event_type"])
    op.create_index("ix_campaign_history_actor_id", "campaign_history", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_campaign_history_actor_id", table_name="campaign_history")
    op.drop_index("ix_campaign_history_event_type", table_name="campaign_history")
    op.drop_index("ix_campaign_history_campaign_id", table_name="campaign_history")
    op.drop_table("campaign_history")
    op.drop_column("campaign_document_associations", "association_evidence")
    op.drop_column("campaign_document_associations", "association_type")
