"""Remove the historical document-governance proposals.

Revision ID: 20260813_0009
Revises: 20260813_0008

The removal discards existing data. The downgrade only reconstructs an empty table
to preserve the structural reversibility of the migration chain.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260813_0009"
down_revision = "20260813_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("knowledge_governance_proposals")


def downgrade() -> None:
    op.create_table(
        "knowledge_governance_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("category_suggestions", sa.JSON(), nullable=False),
        sa.Column("section_suggestions", sa.JSON(), nullable=False),
        sa.Column("review_after_suggestion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("compliance_veto", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("compliance_flags", sa.JSON(), nullable=False),
        sa.Column("compliance_notes", sa.Text(), server_default="", nullable=False),
        sa.Column("retrieval_qa_results", sa.JSON(), nullable=False),
        sa.Column("overall_recommendation", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_governance_proposals_document_id",
        "knowledge_governance_proposals",
        ["document_id"],
    )
    op.create_index(
        "ix_knowledge_governance_proposals_created_by_user_id",
        "knowledge_governance_proposals",
        ["created_by_user_id"],
    )
