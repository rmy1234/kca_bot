"""Add source-document ingestion and reference-question tables."""
from alembic import op
import sqlalchemy as sa

revision = "0006_content_ingestion"
down_revision = "0005_essay_questions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("doc_type", sa.String(30), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("version", sa.String(80), nullable=False, server_default="v1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="처리중"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_source_documents_subject_id", "source_documents", ["subject_id"])
    with op.batch_alter_table("topics") as batch:
        batch.add_column(sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("content_version", sa.String(80), nullable=False, server_default="v1"))
    with op.batch_alter_table("topic_embeddings") as batch:
        batch.add_column(sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("source_documents.id"), nullable=True))
    op.create_index("ix_topic_embeddings_source_document_id", "topic_embeddings", ["source_document_id"])
    op.create_table(
        "reference_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_reference_questions_source_document_id", "reference_questions", ["source_document_id"])
    op.create_index("ix_reference_questions_topic_id", "reference_questions", ["topic_id"])


def downgrade():
    op.drop_index("ix_reference_questions_topic_id", table_name="reference_questions")
    op.drop_index("ix_reference_questions_source_document_id", table_name="reference_questions")
    op.drop_table("reference_questions")
    op.drop_index("ix_topic_embeddings_source_document_id", table_name="topic_embeddings")
    with op.batch_alter_table("topic_embeddings") as batch:
        batch.drop_column("source_document_id")
    with op.batch_alter_table("topics") as batch:
        batch.drop_column("content_version")
        batch.drop_column("last_updated_at")
    op.drop_index("ix_source_documents_subject_id", table_name="source_documents")
    op.drop_table("source_documents")
