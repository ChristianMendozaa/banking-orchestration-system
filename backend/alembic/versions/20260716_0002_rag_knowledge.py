"""Base documental RAG y retiro de FAQ por palabras clave.

Revision ID: 20260716_0002
Revises: 20260716_0001
"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op
from app.db.models import KnowledgeChunk, KnowledgeDocument, RAGInteraction

revision = "20260716_0002"
down_revision = "20260716_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    KnowledgeDocument.__table__.create(bind=bind, checkfirst=True)
    KnowledgeChunk.__table__.create(bind=bind, checkfirst=True)
    RAGInteraction.__table__.create(bind=bind, checkfirst=True)

    inspector = inspect(bind)
    tables = inspector.get_table_names()
    session_columns = {column["name"] for column in inspector.get_columns("kiosk_sessions")}
    if "grounding_status" not in session_columns:
        op.add_column(
            "kiosk_sessions",
            sa.Column(
                "grounding_status",
                sa.String(length=40),
                nullable=False,
                server_default="NOT_APPLICABLE",
            ),
        )
    if "citations_json" not in session_columns:
        op.add_column(
            "kiosk_sessions",
            sa.Column("citations_json", sa.JSON(), nullable=False, server_default="[]"),
        )
    requirement_columns = {column["name"] for column in inspector.get_columns("requirements")}
    for column_name in ("urgency_detected", "security_incident", "distress_detected"):
        if column_name not in requirement_columns:
            op.add_column(
                "requirements",
                sa.Column(column_name, sa.Boolean(), nullable=False, server_default=sa.false()),
            )
    if "faq_entries" in tables:
        op.drop_table("faq_entries")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    requirement_columns = {column["name"] for column in inspector.get_columns("requirements")}
    for column_name in ("distress_detected", "security_incident", "urgency_detected"):
        if column_name in requirement_columns:
            op.drop_column("requirements", column_name)
    session_columns = {column["name"] for column in inspector.get_columns("kiosk_sessions")}
    if "citations_json" in session_columns:
        op.drop_column("kiosk_sessions", "citations_json")
    if "grounding_status" in session_columns:
        op.drop_column("kiosk_sessions", "grounding_status")
    RAGInteraction.__table__.drop(bind=bind, checkfirst=True)
    KnowledgeChunk.__table__.drop(bind=bind, checkfirst=True)
    KnowledgeDocument.__table__.drop(bind=bind, checkfirst=True)

    if "faq_entries" not in inspect(bind).get_table_names():
        op.execute(
            """
            CREATE TABLE faq_entries (
                id UUID PRIMARY KEY,
                category VARCHAR(40) NOT NULL,
                title VARCHAR(160) NOT NULL,
                keywords JSON NOT NULL,
                approved_answer TEXT NOT NULL,
                active BOOLEAN NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
            """
        )
