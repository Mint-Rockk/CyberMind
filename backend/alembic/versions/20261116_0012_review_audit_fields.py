"""Add explicit append-only review and audit fields.

Revision ID: 20261116_0012
Revises: 20261116_0011
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0012"
down_revision: Union[str, Sequence[str], None] = "20261116_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analyst_reviews", sa.Column("evidence_reference", sa.JSON(), nullable=True))
    op.add_column("audit_logs", sa.Column("original_value", sa.JSON(), nullable=True))
    op.add_column("audit_logs", sa.Column("updated_value", sa.JSON(), nullable=True))
    op.add_column("audit_logs", sa.Column("evidence_reference", sa.JSON(), nullable=True))
    op.add_column("audit_logs", sa.Column("decision", sa.String(length=32), nullable=True))
    op.add_column("audit_logs", sa.Column("reason", sa.Text(), nullable=True))
    op.execute("UPDATE analyst_reviews SET evidence_reference = '{}'")
    op.execute("UPDATE audit_logs SET evidence_reference = '{}'")
    op.alter_column("analyst_reviews", "evidence_reference", nullable=False)
    op.alter_column("audit_logs", "evidence_reference", nullable=False)
    op.create_index("ix_audit_logs_decision", "audit_logs", ["decision"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_decision", table_name="audit_logs")
    op.drop_column("audit_logs", "reason")
    op.drop_column("audit_logs", "decision")
    op.drop_column("audit_logs", "evidence_reference")
    op.drop_column("audit_logs", "updated_value")
    op.drop_column("audit_logs", "original_value")
    op.drop_column("analyst_reviews", "evidence_reference")
