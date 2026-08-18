"""Let one kiosk session hold more than one case.

Revision ID: 20260818_0010
Revises: 20260813_0009

`cases.session_id` was unique, which made "one case per kiosk session" a database fact
rather than a policy choice. It is why a customer who asked two things in one breath ("el
horario de la sucursal y además un cargo que no reconozco") only ever got one of them
answered, and why a follow-up question after an automatic answer had no row to occupy and
had to be rejected with a 409.

`tickets.case_id` stays unique: one ticket per case is still correct, and a second case
brings its own ticket. Only the session-to-case fan-out changes.

The downgrade cannot restore the constraint while duplicate rows exist, so it deletes every
case beyond the oldest one per session before re-adding it.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260818_0010"
down_revision = "20260813_0009"
branch_labels = None
depends_on = None

_CONSTRAINT = "cases_session_id_key"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {constraint["name"] for constraint in inspector.get_unique_constraints("cases")} | {
        index["name"] for index in inspector.get_indexes("cases") if index.get("unique")
    }
    for name in existing:
        # SQLite reflects the same constraint as a unique index and Postgres names it after
        # the column, so drop whichever form this backend actually produced.
        if name and "session_id" in name:
            op.drop_constraint(name, "cases", type_="unique")
    # `ix_cases_session_id` from the initial migration is non-unique and still wanted: every
    # lookup of a session's cases goes through it.


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM cases
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT DISTINCT ON (session_id) id
                FROM cases
                ORDER BY session_id, created_at
            ) AS oldest_per_session
        )
        """
    )
    op.create_unique_constraint(_CONSTRAINT, "cases", ["session_id"])
