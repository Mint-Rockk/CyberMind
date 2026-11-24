"""Add ATT&CK dataset and mapping provenance metadata.

Revision ID: 20261116_0005
Revises: 20261116_0004
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0005"
down_revision: Union[str, Sequence[str], None] = "20261116_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attack_techniques", sa.Column("object_type", sa.String(64), nullable=True))
    op.add_column("attack_techniques", sa.Column("aliases", sa.JSON(), nullable=True))
    op.add_column("attack_techniques", sa.Column("external_references", sa.JSON(), nullable=True))
    op.add_column("attack_techniques", sa.Column("dataset_version", sa.String(64), nullable=True))
    op.add_column("document_technique_mappings", sa.Column("mapping_status", sa.String(32), nullable=True))
    op.add_column("document_technique_mappings", sa.Column("dataset_version", sa.String(64), nullable=True))
    op.execute(
        """
        UPDATE attack_techniques
        SET object_type = 'attack-pattern',
            aliases = '[]',
            external_references = '[]'
        """
    )
    op.execute(
        """
        UPDATE document_technique_mappings
        SET mapping_status = 'inferred'
        """
    )
    op.alter_column("attack_techniques", "object_type", nullable=False)
    op.alter_column("attack_techniques", "aliases", nullable=False)
    op.alter_column("attack_techniques", "external_references", nullable=False)
    op.alter_column("document_technique_mappings", "mapping_status", nullable=False)
    op.create_index("ix_attack_techniques_object_type", "attack_techniques", ["object_type"])
    op.create_index("ix_attack_techniques_dataset_version", "attack_techniques", ["dataset_version"])


def downgrade() -> None:
    op.drop_index("ix_attack_techniques_dataset_version", table_name="attack_techniques")
    op.drop_index("ix_attack_techniques_object_type", table_name="attack_techniques")
    for column in ("dataset_version", "mapping_status"):
        op.drop_column("document_technique_mappings", column)
    for column in ("dataset_version", "external_references", "aliases", "object_type"):
        op.drop_column("attack_techniques", column)
