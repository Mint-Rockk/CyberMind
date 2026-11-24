"""Add binary PDF storage for generated reports.

Revision ID: 20261116_0011
Revises: 20261116_0010
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0011"
down_revision: Union[str, Sequence[str], None] = "20261116_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generated_reports", sa.Column("content_bytes", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("generated_reports", "content_bytes")
