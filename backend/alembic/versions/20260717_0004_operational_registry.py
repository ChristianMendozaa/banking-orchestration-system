"""Registro operativo y estimacion de espera.

Revision ID: 20260717_0004
Revises: 20260716_0003
"""

import sqlalchemy as sa

from alembic import op

revision = "20260717_0004"
down_revision = "20260716_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("demo_clients", "client_references")
    op.alter_column(
        "identifications",
        "demo_client_id",
        new_column_name="client_reference_id",
        existing_type=sa.Uuid(),
        existing_nullable=True,
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER INDEX IF EXISTS ix_demo_clients_identifier_hash "
            "RENAME TO ix_client_references_identifier_hash"
        )

    op.add_column(
        "tickets",
        sa.Column("estimated_wait_minutes", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE tickets
        SET estimated_wait_minutes = CASE
            WHEN automatic THEN 0
            WHEN executive_id IS NOT NULL THEN 8
            ELSE NULL
        END
        """
    )
    op.execute(
        """
        UPDATE knowledge_documents
        SET source_type = 'INTERNAL'
        WHERE source_type = 'SIMULATED'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE knowledge_documents
        SET source_type = 'SIMULATED'
        WHERE source_type = 'INTERNAL'
        """
    )
    op.drop_column("tickets", "estimated_wait_minutes")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER INDEX IF EXISTS ix_client_references_identifier_hash "
            "RENAME TO ix_demo_clients_identifier_hash"
        )
    op.alter_column(
        "identifications",
        "client_reference_id",
        new_column_name="demo_client_id",
        existing_type=sa.Uuid(),
        existing_nullable=True,
    )
    op.rename_table("client_references", "demo_clients")
