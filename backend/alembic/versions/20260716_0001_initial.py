"""Esquema inicial congelado del sistema.

Revision ID: 20260716_0001
Revises:
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "20260716_0001"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def uuid_id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), nullable=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "executives",
        uuid_id(),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("window_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("last_assigned_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_executives_status", "executives", ["status"])

    op.create_table(
        "users",
        uuid_id(),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("executive_id", sa.Uuid()),
        *timestamps(),
        sa.ForeignKeyConstraint(["executive_id"], ["executives.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("executive_id"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "refresh_sessions",
        uuid_id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])
    op.create_index("ix_refresh_sessions_token_hash", "refresh_sessions", ["token_hash"])

    op.create_table(
        "demo_clients",
        uuid_id(),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("identifier_hash", sa.String(64), nullable=False),
        sa.Column("masked_identifier", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identifier_hash"),
    )
    op.create_index("ix_demo_clients_identifier_hash", "demo_clients", ["identifier_hash"])

    op.create_table(
        "executive_skills",
        uuid_id(),
        sa.Column("executive_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("experience_level", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        *timestamps(),
        sa.ForeignKeyConstraint(["executive_id"], ["executives.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("executive_id", "category"),
    )
    op.create_index("ix_executive_skills_executive_id", "executive_skills", ["executive_id"])
    op.create_index("ix_executive_skills_category", "executive_skills", ["category"])

    op.create_table(
        "kiosk_sessions",
        uuid_id(),
        sa.Column("access_token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("preferential_attention", sa.Boolean(), nullable=False),
        sa.Column("clarification_count", sa.Integer(), nullable=False),
        sa.Column("correction_count", sa.Integer(), nullable=False),
        sa.Column("resolution_type", sa.String(40)),
        sa.Column("final_response", sa.Text()),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_token_hash"),
    )
    op.create_index("ix_kiosk_sessions_access_token_hash", "kiosk_sessions", ["access_token_hash"])
    op.create_index("ix_kiosk_sessions_status", "kiosk_sessions", ["status"])

    op.create_table(
        "requirements",
        uuid_id(),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("masked_text", sa.Text(), nullable=False),
        sa.Column("pii_metadata", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("consultation_level", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("ambiguous", sa.Boolean(), nullable=False),
        sa.Column("clarification_question", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("force_human", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["session_id"], ["kiosk_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "turn_id"),
    )
    op.create_index("ix_requirements_session_id", "requirements", ["session_id"])
    op.create_index("ix_requirements_turn_id", "requirements", ["turn_id"])
    op.create_index("ix_requirements_category", "requirements", ["category"])
    op.create_index("ix_requirements_consultation_level", "requirements", ["consultation_level"])

    op.create_table(
        "cases",
        uuid_id(),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("priority", sa.String(40)),
        sa.Column("consultation_level", sa.String(40), nullable=False),
        sa.Column("identification_status", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("preferential_attention", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("force_human", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["kiosk_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index("ix_cases_session_id", "cases", ["session_id"])
    op.create_index("ix_cases_category", "cases", ["category"])
    op.create_index("ix_cases_priority", "cases", ["priority"])
    op.create_index("ix_cases_status", "cases", ["status"])
    op.create_index("ix_cases_consultation_level", "cases", ["consultation_level"])
    op.create_index("ix_cases_category_priority", "cases", ["category", "priority"])

    op.create_table(
        "identifications",
        uuid_id(),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("demo_client_id", sa.Uuid()),
        sa.Column("identifier_hash", sa.String(64), nullable=False),
        sa.Column("masked_identifier", sa.String(32), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["demo_client_id"], ["demo_clients.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id"),
    )
    op.create_index("ix_identifications_case_id", "identifications", ["case_id"])

    op.create_table(
        "tickets",
        sa.Column("number", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("executive_id", sa.Uuid()),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("automatic", sa.Boolean(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["executive_id"], ["executives.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("number"),
        sa.UniqueConstraint("case_id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_tickets_public_id", "tickets", ["public_id"])
    op.create_index("ix_tickets_case_id", "tickets", ["case_id"])
    op.create_index("ix_tickets_executive_id", "tickets", ["executive_id"])
    op.create_index("ix_tickets_status", "tickets", ["status"])
    op.create_index("ix_tickets_executive_status", "tickets", ["executive_id", "status"])

    op.create_table(
        "trace_events",
        uuid_id(),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trace_events_case_id", "trace_events", ["case_id"])
    op.create_index("ix_trace_events_event_type", "trace_events", ["event_type"])

    op.create_table(
        "faq_entries",
        uuid_id(),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("approved_answer", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    for table in (
        "faq_entries",
        "trace_events",
        "tickets",
        "identifications",
        "cases",
        "requirements",
        "kiosk_sessions",
        "executive_skills",
        "demo_clients",
        "refresh_sessions",
        "users",
        "executives",
    ):
        op.drop_table(table)
