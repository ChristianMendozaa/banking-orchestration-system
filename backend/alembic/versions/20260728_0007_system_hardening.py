"""Controles operativos y cola de indexacion documental.

Revision ID: 20260728_0007
Revises: 20260721_0006
"""

import sqlalchemy as sa

from alembic import op

revision = "20260728_0007"
down_revision = "20260721_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("executives") as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))

    with op.batch_alter_table("requirements") as batch_op:
        batch_op.add_column(
            sa.Column(
                "classification_source",
                sa.String(length=20),
                server_default="FALLBACK",
                nullable=False,
            )
        )

    op.create_table(
        "knowledge_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_jobs_document_id", "knowledge_jobs", ["document_id"])
    op.create_index("ix_knowledge_jobs_operation", "knowledge_jobs", ["operation"])
    op.create_index("ix_knowledge_jobs_status", "knowledge_jobs", ["status"])
    op.create_index(
        "ix_knowledge_jobs_created_by_user_id",
        "knowledge_jobs",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_knowledge_jobs_queue",
        "knowledge_jobs",
        ["status", "created_at"],
    )
    op.create_table(
        "operational_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operational_audit_events_actor_user_id",
        "operational_audit_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_operational_audit_events_action",
        "operational_audit_events",
        ["action"],
    )
    op.create_index(
        "ix_operational_audit_events_target_type",
        "operational_audit_events",
        ["target_type"],
    )
    op.create_index(
        "ix_operational_audit_events_target_id",
        "operational_audit_events",
        ["target_id"],
    )

    # Los datos recuperables de identificacion dejan de existir al cerrar el caso.
    op.execute(
        """
        UPDATE identifications
        SET identifier_ciphertext = NULL,
            identifier_nonce = NULL,
            identifier_key_id = NULL
        WHERE EXISTS (
            SELECT 1
            FROM tickets
            WHERE tickets.case_id = identifications.case_id
              AND tickets.status = 'CERRADO'
        )
        """
    )
    # Un caso humano sin ejecutivo queda explicitamente en cola.
    op.execute(
        """
        UPDATE cases
        SET status = 'QUEUED'
        WHERE EXISTS (
            SELECT 1
            FROM tickets
            WHERE tickets.case_id = cases.id
              AND tickets.status = 'PENDIENTE'
              AND tickets.automatic = false
              AND tickets.executive_id IS NULL
        )
        """
    )


def downgrade() -> None:
    # La revisión anterior no reconoce QUEUED; se conserva el caso como asignado.
    op.execute("UPDATE cases SET status = 'ASSIGNED' WHERE status = 'QUEUED'")
    op.drop_index(
        "ix_operational_audit_events_target_id",
        table_name="operational_audit_events",
    )
    op.drop_index(
        "ix_operational_audit_events_target_type",
        table_name="operational_audit_events",
    )
    op.drop_index(
        "ix_operational_audit_events_action",
        table_name="operational_audit_events",
    )
    op.drop_index(
        "ix_operational_audit_events_actor_user_id",
        table_name="operational_audit_events",
    )
    op.drop_table("operational_audit_events")
    op.drop_index("ix_knowledge_jobs_queue", table_name="knowledge_jobs")
    op.drop_index("ix_knowledge_jobs_created_by_user_id", table_name="knowledge_jobs")
    op.drop_index("ix_knowledge_jobs_status", table_name="knowledge_jobs")
    op.drop_index("ix_knowledge_jobs_operation", table_name="knowledge_jobs")
    op.drop_index("ix_knowledge_jobs_document_id", table_name="knowledge_jobs")
    op.drop_table("knowledge_jobs")

    with op.batch_alter_table("requirements") as batch_op:
        batch_op.drop_column("classification_source")
    with op.batch_alter_table("executives") as batch_op:
        batch_op.drop_column("version")
