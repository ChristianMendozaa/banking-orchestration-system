"""Count consecutive declined turns so a decline no longer ends the session.

Revision ID: 20261019_0013
Revises: 20260825_0012
"""

import sqlalchemy as sa

from alembic import op

revision = "20261019_0013"
down_revision = "20260825_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kiosk_sessions",
        sa.Column("decline_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("kiosk_sessions", "decline_count")
