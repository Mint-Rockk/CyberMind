"""Add grounded GenAI investigation input/output storage.

Revision ID: 20261116_0009
Revises: 20261116_0008
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0009"
down_revision: Union[str, Sequence[str], None] = "20261116_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("investigations", sa.Column("request_query", sa.Text(), nullable=True))
    op.add_column("investigations", sa.Column("retrieval_context", sa.Text(), nullable=True))
    op.add_column("investigations", sa.Column("evidence_references", sa.JSON(), nullable=True))
    op.add_column("investigations", sa.Column("model_output", sa.JSON(), nullable=True))
    op.add_column("investigations", sa.Column("provider_metadata", sa.JSON(), nullable=True))
    op.add_column("investigations", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("investigations", sa.Column("error_message", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE investigations
        SET evidence_references = '[]',
            model_output = '{}',
            provider_metadata = '{}'
        """
    )
    op.alter_column("investigations", "evidence_references", nullable=False)
    op.alter_column("investigations", "model_output", nullable=False)
    op.alter_column("investigations", "provider_metadata", nullable=False)


def downgrade() -> None:
    op.drop_column("investigations", "error_message")
    op.drop_column("investigations", "completed_at")
    op.drop_column("investigations", "provider_metadata")
    op.drop_column("investigations", "model_output")
    op.drop_column("investigations", "evidence_references")
    op.drop_column("investigations", "retrieval_context")
    op.drop_column("investigations", "request_query")
