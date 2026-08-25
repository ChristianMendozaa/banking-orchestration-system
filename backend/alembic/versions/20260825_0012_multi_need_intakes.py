"""Persist multiple needs from one kiosk turn and case-local outcomes.

Revision ID: 20260825_0012
Revises: 20260824_0011
"""

import sqlalchemy as sa

from alembic import op

revision = "20260825_0012"
down_revision = "20260824_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("requirements") as batch_op:
        batch_op.add_column(
            sa.Column("need_index", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.drop_constraint("uq_requirements_session_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_requirements_session_turn_need", ["session_id", "turn_id", "need_index"]
        )

    with op.batch_alter_table("cases") as batch_op:
        batch_op.add_column(sa.Column("resolution_type", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("final_response", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "grounding_status",
                sa.String(length=40),
                nullable=False,
                server_default="NOT_APPLICABLE",
            )
        )
        batch_op.add_column(
            sa.Column("citations_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("grounding_detail_json", sa.JSON(), nullable=False, server_default="{}")
        )

    # Session outcome columns held only the newest case's value. Preserve that value on the
    # newest historical case; older cases cannot be reconstructed and keep neutral defaults.
    op.execute(
        """
        UPDATE cases AS c
        SET resolution_type = s.resolution_type,
            final_response = s.final_response,
            grounding_status = s.grounding_status,
            citations_json = s.citations_json,
            grounding_detail_json = s.grounding_detail_json
        FROM kiosk_sessions AS s
        WHERE c.session_id = s.id
          AND c.id = (
              SELECT c2.id FROM cases AS c2
              WHERE c2.session_id = c.session_id
              ORDER BY c2.created_at DESC LIMIT 1
          )
        """
    )


def downgrade() -> None:
    # The legacy schema can store only one requirement per turn. Remove secondary
    # cases first so their RESTRICT requirement FK never makes the downgrade fail;
    # case-owned tickets and identifications are removed by their CASCADE FKs.
    op.execute(
        """
        DELETE FROM cases
        WHERE requirement_id IN (
            SELECT id FROM requirements WHERE need_index > 0
        )
        """
    )
    op.execute("DELETE FROM requirements WHERE need_index > 0")
    with op.batch_alter_table("cases") as batch_op:
        batch_op.drop_column("grounding_detail_json")
        batch_op.drop_column("citations_json")
        batch_op.drop_column("grounding_status")
        batch_op.drop_column("final_response")
        batch_op.drop_column("resolution_type")
    with op.batch_alter_table("requirements") as batch_op:
        batch_op.drop_constraint("uq_requirements_session_turn_need", type_="unique")
        batch_op.create_unique_constraint("uq_requirements_session_id", ["session_id", "turn_id"])
        batch_op.drop_column("need_index")
