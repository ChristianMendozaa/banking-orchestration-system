"""Expediente operativo, conversacion protegida y cierre documentado.

Revision ID: 20260721_0006
Revises: 20260720_0005
"""

import sqlalchemy as sa

from alembic import op

revision = "20260721_0006"
down_revision = "20260720_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("external_item_id", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("masked_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["kiosk_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "external_item_id"),
    )
    op.create_index("ix_conversation_messages_session_id", "conversation_messages", ["session_id"])
    op.create_index("ix_conversation_messages_role", "conversation_messages", ["role"])
    op.create_index("ix_conversation_messages_created_at", "conversation_messages", ["created_at"])

    with op.batch_alter_table("identifications") as batch_op:
        batch_op.add_column(sa.Column("identifier_ciphertext", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("identifier_nonce", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("identifier_key_id", sa.String(length=80), nullable=True))

    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("resolution_outcome", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("resolution_note", sa.Text(), nullable=True))

    op.execute(
        """
        WITH ranked AS (
            SELECT
                number,
                ROW_NUMBER() OVER (
                    PARTITION BY executive_id
                    ORDER BY started_at ASC NULLS LAST, created_at ASC, number ASC
                ) AS position
            FROM tickets
            WHERE status = 'EN_ATENCION' AND executive_id IS NOT NULL
        )
        UPDATE tickets
        SET status = 'PENDIENTE', started_at = NULL, version = version + 1
        FROM ranked
        WHERE tickets.number = ranked.number AND ranked.position > 1
        """
    )
    op.execute(
        """
        UPDATE executives
        SET status = 'OCUPADO'
        WHERE status <> 'INACTIVO'
          AND id IN (
              SELECT executive_id
              FROM tickets
              WHERE status = 'EN_ATENCION' AND executive_id IS NOT NULL
          )
        """
    )

    op.create_index(
        "uq_tickets_one_active_per_executive",
        "tickets",
        ["executive_id"],
        unique=True,
        postgresql_where=sa.text("status = 'EN_ATENCION'"),
    )


def downgrade() -> None:
    op.drop_index("uq_tickets_one_active_per_executive", table_name="tickets")
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("resolution_note")
        batch_op.drop_column("resolution_outcome")
    with op.batch_alter_table("identifications") as batch_op:
        batch_op.drop_column("identifier_key_id")
        batch_op.drop_column("identifier_nonce")
        batch_op.drop_column("identifier_ciphertext")
    op.drop_index("ix_conversation_messages_created_at", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_role", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_session_id", table_name="conversation_messages")
    op.drop_table("conversation_messages")
