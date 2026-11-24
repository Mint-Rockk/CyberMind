"""Add explainable document classification and prioritisation fields.

Revision ID: 20261116_0004
Revises: 20261116_0003
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0004"
down_revision: Union[str, Sequence[str], None] = "20261116_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cti_documents", sa.Column("classification_category", sa.String(64), nullable=True))
    op.add_column("cti_documents", sa.Column("classification_confidence", sa.Float(), nullable=True))
    op.add_column("cti_documents", sa.Column("classification_method", sa.String(128), nullable=True))
    op.add_column("cti_documents", sa.Column("classification_evidence", sa.JSON(), nullable=True))
    op.add_column("cti_documents", sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cti_documents", sa.Column("priority_score", sa.Float(), nullable=True))
    op.add_column("cti_documents", sa.Column("priority_factors", sa.JSON(), nullable=True))
    op.add_column("cti_documents", sa.Column("priority_method", sa.String(128), nullable=True))
    op.add_column("cti_documents", sa.Column("prioritized_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_cti_documents_classification_category", "cti_documents", ["classification_category"])
    op.create_index("ix_cti_documents_priority_score", "cti_documents", ["priority_score"])


def downgrade() -> None:
    op.drop_index("ix_cti_documents_priority_score", table_name="cti_documents")
    op.drop_index("ix_cti_documents_classification_category", table_name="cti_documents")
    for column in (
        "prioritized_at",
        "priority_method",
        "priority_factors",
        "priority_score",
        "classified_at",
        "classification_evidence",
        "classification_method",
        "classification_confidence",
        "classification_category",
    ):
        op.drop_column("cti_documents", column)
