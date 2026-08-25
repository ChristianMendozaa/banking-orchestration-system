"""Persist unresolved intent and add hybrid knowledge search support.

Revision ID: 20260824_0011
Revises: 20260818_0010
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260824_0011"
down_revision = "20260818_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgresql_dialect = op.get_bind().dialect.name == "postgresql"
    if postgresql_dialect:
        op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.add_column("kiosk_sessions", sa.Column("grounding_detail_json", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE kiosk_sessions SET grounding_detail_json = '{}' WHERE grounding_detail_json IS NULL"
    )
    op.alter_column("kiosk_sessions", "grounding_detail_json", nullable=False)

    op.add_column("requirements", sa.Column("routing_category", sa.String(40), nullable=True))
    op.add_column(
        "requirements",
        sa.Column(
            "clarification_outcome", sa.String(40), nullable=False, server_default="NOT_APPLICABLE"
        ),
    )
    op.add_column(
        "requirements",
        sa.Column("intent_status", sa.String(40), nullable=False, server_default="CONFIRMED"),
    )
    op.add_column(
        "requirements",
        sa.Column("confirmation_kind", sa.String(40), nullable=False, server_default="INTENT"),
    )
    op.add_column("requirements", sa.Column("handoff_summary", sa.Text(), nullable=True))
    op.execute("UPDATE requirements SET routing_category = category WHERE routing_category IS NULL")
    op.alter_column("requirements", "routing_category", nullable=False)
    op.create_index("ix_requirements_routing_category", "requirements", ["routing_category"])

    op.add_column("knowledge_chunks", sa.Column("search_text", sa.Text(), nullable=True))
    normalization = "lower(unaccent(concat_ws(' ', document.title, chunk.section, chunk.content)))"
    if not postgresql_dialect:
        normalization = "lower(concat_ws(' ', document.title, chunk.section, chunk.content))"
    op.execute(
        f"""
        UPDATE knowledge_chunks AS chunk
        SET search_text = {normalization}
        FROM knowledge_documents AS document
        WHERE document.id = chunk.document_id
        """
    )
    op.execute("UPDATE knowledge_chunks SET search_text = '' WHERE search_text IS NULL")
    op.alter_column("knowledge_chunks", "search_text", nullable=False)

    op.add_column("rag_interactions", sa.Column("correlation_id", sa.String(80), nullable=True))
    op.add_column("rag_interactions", sa.Column("details_json", sa.JSON(), nullable=True))
    op.execute("UPDATE rag_interactions SET details_json = '{}' WHERE details_json IS NULL")
    op.alter_column("rag_interactions", "details_json", nullable=False)
    op.create_index("ix_rag_interactions_correlation_id", "rag_interactions", ["correlation_id"])

    if postgresql_dialect:
        op.add_column(
            "knowledge_chunks",
            sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        )
        op.execute(
            "UPDATE knowledge_chunks SET search_vector = "
            "to_tsvector('spanish', unaccent(search_text))"
        )
        op.execute(
            """
            CREATE FUNCTION knowledge_chunks_search_vector_update() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector := to_tsvector('spanish', unaccent(NEW.search_text));
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER knowledge_chunks_search_vector_trigger
            BEFORE INSERT OR UPDATE OF search_text ON knowledge_chunks
            FOR EACH ROW EXECUTE FUNCTION knowledge_chunks_search_vector_update()
            """
        )
        op.create_index(
            "ix_knowledge_chunks_search_vector",
            "knowledge_chunks",
            ["search_vector"],
            postgresql_using="gin",
        )
        op.create_index(
            "ix_knowledge_chunks_search_text_trgm",
            "knowledge_chunks",
            ["search_text"],
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS knowledge_chunks_search_vector_trigger ON knowledge_chunks"
        )
        op.execute("DROP FUNCTION IF EXISTS knowledge_chunks_search_vector_update()")
        op.drop_index("ix_knowledge_chunks_search_text_trgm", table_name="knowledge_chunks")
        op.drop_index("ix_knowledge_chunks_search_vector", table_name="knowledge_chunks")
        op.drop_column("knowledge_chunks", "search_vector")
    op.drop_index("ix_rag_interactions_correlation_id", table_name="rag_interactions")
    op.drop_column("rag_interactions", "details_json")
    op.drop_column("rag_interactions", "correlation_id")
    op.drop_column("knowledge_chunks", "search_text")
    op.drop_index("ix_requirements_routing_category", table_name="requirements")
    op.drop_column("requirements", "handoff_summary")
    op.drop_column("requirements", "confirmation_kind")
    op.drop_column("requirements", "intent_status")
    op.drop_column("requirements", "clarification_outcome")
    op.drop_column("requirements", "routing_category")
    op.drop_column("kiosk_sessions", "grounding_detail_json")
