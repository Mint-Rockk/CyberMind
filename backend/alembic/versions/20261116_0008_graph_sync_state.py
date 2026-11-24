"""Add PostgreSQL-backed Neo4j synchronization state.

Revision ID: 20261116_0008
Revises: 20261116_0007
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0008"
down_revision: Union[str, Sequence[str], None] = "20261116_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_sync_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_graph_sync_states_resource"),
    )
    op.create_index("ix_graph_sync_states_resource_id", "graph_sync_states", ["resource_id"])
    op.create_index("ix_graph_sync_states_status", "graph_sync_states", ["status"])


def downgrade() -> None:
    op.drop_index("ix_graph_sync_states_status", table_name="graph_sync_states")
    op.drop_index("ix_graph_sync_states_resource_id", table_name="graph_sync_states")
    op.drop_table("graph_sync_states")
