"""Resumen conversacional e idempotencia de confirmacion.

Revision ID: 20260720_0005
Revises: 20260717_0004
"""

import sqlalchemy as sa

from alembic import op

revision = "20260720_0005"
down_revision = "20260717_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("requirements") as batch_op:
        batch_op.add_column(
            sa.Column(
                "customer_summary",
                sa.Text(),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("confirmation_decision", sa.Boolean(), nullable=True))

    op.execute(
        """
        UPDATE requirements
        SET customer_summary = CASE category
            WHEN 'REPORTE_FRAUDE'
                THEN 'Necesitas reportar un posible fraude o un movimiento no reconocido.'
            WHEN 'BLOQUEO_TARJETA'
                THEN 'Necesitas bloquear una tarjeta.'
            WHEN 'BANCA_DIGITAL'
                THEN 'Necesitas ayuda con la banca digital.'
            WHEN 'SOLICITUD_CREDITO'
                THEN 'Quieres información o ayuda con una solicitud de crédito.'
            ELSE 'Necesitas orientación sobre una consulta bancaria.'
        END
        WHERE customer_summary IS NULL
        """
    )
    op.execute(
        """
        UPDATE requirements
        SET confirmation_decision = CASE
            WHEN EXISTS (
                SELECT 1 FROM cases WHERE cases.requirement_id = requirements.id
            ) THEN TRUE
            WHEN active = FALSE AND ambiguous = FALSE THEN FALSE
            ELSE NULL
        END
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY session_id
                    ORDER BY created_at DESC, id DESC
                ) AS position
            FROM requirements
            WHERE active = TRUE
        )
        UPDATE requirements
        SET active = FALSE
        FROM ranked
        WHERE requirements.id = ranked.id
          AND ranked.position > 1
        """
    )

    with op.batch_alter_table("requirements") as batch_op:
        batch_op.alter_column(
            "customer_summary",
            existing_type=sa.Text(),
            nullable=False,
            server_default="Necesitas orientación sobre una consulta bancaria.",
        )


def downgrade() -> None:
    with op.batch_alter_table("requirements") as batch_op:
        batch_op.drop_column("confirmation_decision")
        batch_op.drop_column("customer_summary")
