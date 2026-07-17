"""Expiracion, prioridad previa y gestion documental.

Revision ID: 20260716_0003
Revises: 20260716_0002
"""

import sqlalchemy as sa

from alembic import op

revision = "20260716_0003"
down_revision = "20260716_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kiosk_sessions",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_kiosk_sessions_expires_at", "kiosk_sessions", ["expires_at"])
    op.alter_column("kiosk_sessions", "expires_at", server_default=None)

    op.add_column(
        "requirements",
        sa.Column("proposed_priority", sa.String(40), nullable=True),
    )
    op.execute(
        """
        UPDATE requirements
        SET proposed_priority = CASE
            WHEN category = 'REPORTE_FRAUDE' THEN 'CRITICO'
            WHEN category = 'BLOQUEO_TARJETA' THEN 'ALTO'
            WHEN category IN ('SOLICITUD_CREDITO', 'BANCA_DIGITAL') THEN 'MEDIO'
            ELSE 'BAJO'
        END
        """
    )
    op.alter_column("requirements", "proposed_priority", nullable=False)
    op.create_index("ix_requirements_proposed_priority", "requirements", ["proposed_priority"])

    columns = (
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column(
            "mime_type",
            sa.String(100),
            nullable=False,
            server_default="application/pdf",
        ),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "index_status",
            sa.String(40),
            nullable=False,
            server_default="READY",
        ),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.Column("index_error", sa.Text()),
        sa.Column("created_by_user_id", sa.Uuid()),
    )
    for column in columns:
        op.add_column("knowledge_documents", column)
    op.execute("UPDATE knowledge_documents SET storage_key = CAST(id AS VARCHAR(64)) || '.pdf'")
    op.alter_column("knowledge_documents", "storage_key", nullable=False)
    op.create_unique_constraint(
        "uq_knowledge_documents_storage_key",
        "knowledge_documents",
        ["storage_key"],
    )
    op.create_foreign_key(
        "fk_knowledge_documents_created_by_user_id_users",
        "knowledge_documents",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_knowledge_documents_created_by_user_id",
        "knowledge_documents",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_knowledge_documents_index_status",
        "knowledge_documents",
        ["index_status"],
    )
    for column_name in ("mime_type", "byte_size", "page_count", "index_status"):
        op.alter_column("knowledge_documents", column_name, server_default=None)


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_index_status", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_created_by_user_id", table_name="knowledge_documents")
    op.drop_constraint(
        "fk_knowledge_documents_created_by_user_id_users",
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_knowledge_documents_storage_key",
        "knowledge_documents",
        type_="unique",
    )
    for column_name in (
        "created_by_user_id",
        "index_error",
        "indexed_at",
        "index_status",
        "page_count",
        "byte_size",
        "mime_type",
        "storage_key",
    ):
        op.drop_column("knowledge_documents", column_name)
    op.drop_index("ix_requirements_proposed_priority", table_name="requirements")
    op.drop_column("requirements", "proposed_priority")
    op.drop_index("ix_kiosk_sessions_expires_at", table_name="kiosk_sessions")
    op.drop_column("kiosk_sessions", "expires_at")
