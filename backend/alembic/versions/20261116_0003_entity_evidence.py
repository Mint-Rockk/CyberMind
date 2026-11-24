"""Add auditable entity evidence fields.

Revision ID: 20261116_0003
Revises: 20261116_0002
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0003"
down_revision: Union[str, Sequence[str], None] = "20261116_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("document_entity_associations", sa.Column("evidence_text", sa.Text(), nullable=True))
    op.add_column("document_entity_associations", sa.Column("evidence_start", sa.Integer(), nullable=True))
    op.add_column("document_entity_associations", sa.Column("evidence_end", sa.Integer(), nullable=True))
    op.add_column(
        "document_entity_associations",
        sa.Column("extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("document_entity_associations", "extracted_at")
    op.drop_column("document_entity_associations", "evidence_end")
    op.drop_column("document_entity_associations", "evidence_start")
    op.drop_column("document_entity_associations", "evidence_text")
