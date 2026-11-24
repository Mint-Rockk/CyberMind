"""Add document normalization and duplicate tracking fields.

Revision ID: 20261116_0002
Revises: 20261116_0001
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261116_0002"
down_revision: Union[str, Sequence[str], None] = "20261116_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_source_records",
        sa.Column("raw_content", sa.Text(), nullable=True),
    )
    op.add_column(
        "cti_documents",
        sa.Column("original_title", sa.String(1000), nullable=True),
    )
    op.add_column(
        "cti_documents",
        sa.Column("normalized_title", sa.String(1000), nullable=True),
    )
    op.add_column(
        "cti_documents",
        sa.Column("normalized_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "cti_documents",
        sa.Column("original_url", sa.String(2048), nullable=True),
    )
    op.add_column(
        "cti_documents",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "cti_documents",
        sa.Column("document_type", sa.String(64), nullable=True),
    )
    op.add_column(
        "cti_documents",
        sa.Column("normalization_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "cti_documents",
        sa.Column(
            "duplicate_of_document_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "cti_documents",
        sa.Column("duplicate_relationship", sa.String(32), nullable=True),
    )
    op.create_foreign_key(
        "fk_cti_documents_duplicate_of_document_id_cti_documents",
        "cti_documents",
        "cti_documents",
        ["duplicate_of_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE cti_documents
        SET original_title = title,
            normalized_title = title,
            normalized_text = normalized_content,
            original_url = '',
            content_hash = '',
            document_type = 'unknown',
            normalization_status = 'normalized'
        """
    )
    for column in (
        "original_title",
        "normalized_title",
        "normalized_text",
        "original_url",
        "content_hash",
        "document_type",
        "normalization_status",
    ):
        op.alter_column("cti_documents", column, nullable=False)
    op.create_index("ix_cti_documents_content_hash", "cti_documents", ["content_hash"])
    op.create_index("ix_cti_documents_document_type", "cti_documents", ["document_type"])
    op.create_index(
        "ix_cti_documents_normalization_status",
        "cti_documents",
        ["normalization_status"],
    )
    op.create_index(
        "ix_cti_documents_duplicate_of_document_id",
        "cti_documents",
        ["duplicate_of_document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cti_documents_duplicate_of_document_id", table_name="cti_documents")
    op.drop_index("ix_cti_documents_normalization_status", table_name="cti_documents")
    op.drop_index("ix_cti_documents_document_type", table_name="cti_documents")
    op.drop_index("ix_cti_documents_content_hash", table_name="cti_documents")
    op.drop_constraint(
        "fk_cti_documents_duplicate_of_document_id_cti_documents",
        "cti_documents",
        type_="foreignkey",
    )
    for column in (
        "duplicate_relationship",
        "duplicate_of_document_id",
        "normalization_status",
        "document_type",
        "content_hash",
        "original_url",
        "normalized_text",
        "normalized_title",
        "original_title",
    ):
        op.drop_column("cti_documents", column)
    op.drop_column("raw_source_records", "raw_content")
