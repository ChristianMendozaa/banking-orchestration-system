"""RAG document base and retirement of keyword-based FAQ.

Revision ID: 20260716_0002
Revises: 20260716_0001
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "20260716_0002"
down_revision = "20260716_0001"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_urls", sa.JSON(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_after", sa.DateTime(timezone=True)),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", "version"),
    )
    op.create_index("ix_knowledge_documents_slug", "knowledge_documents", ["slug"])
    op.create_index("ix_knowledge_documents_source_type", "knowledge_documents", ["source_type"])
    op.create_index(
        "ix_knowledge_documents_content_sha256", "knowledge_documents", ["content_sha256"]
    )
    op.create_index("ix_knowledge_documents_active", "knowledge_documents", ["active"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(240)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "ordinal"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_content_sha256", "knowledge_chunks", ["content_sha256"])
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_knowledge_chunks_embedding_hnsw "
            "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
        )

    op.create_table(
        "rag_interactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid()),
        sa.Column("masked_query", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("retrieved_json", sa.JSON(), nullable=False),
        sa.Column("answer_sha256", sa.String(64)),
        *timestamps(),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_interactions_case_id", "rag_interactions", ["case_id"])
    op.create_index("ix_rag_interactions_outcome", "rag_interactions", ["outcome"])

    op.add_column(
        "kiosk_sessions",
        sa.Column(
            "grounding_status",
            sa.String(40),
            nullable=False,
            server_default="NOT_APPLICABLE",
        ),
    )
    op.add_column(
        "kiosk_sessions",
        sa.Column("citations_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    for column_name in ("urgency_detected", "security_incident", "distress_detected"):
        op.add_column(
            "requirements",
            sa.Column(column_name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.drop_table("faq_entries")


def downgrade() -> None:
    op.create_table(
        "faq_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("approved_answer", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in ("distress_detected", "security_incident", "urgency_detected"):
        op.drop_column("requirements", column_name)
    op.drop_column("kiosk_sessions", "citations_json")
    op.drop_column("kiosk_sessions", "grounding_status")
    op.drop_table("rag_interactions")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
