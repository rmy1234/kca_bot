"""Add RAG embeddings and generation audit logs."""
from alembic import op
import sqlalchemy as sa

revision = "0003_rag_pipeline"
down_revision = "0002_problem_bank"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "topic_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
    )
    op.create_index("ix_topic_embeddings_topic_id", "topic_embeddings", ["topic_id"])
    op.create_table(
        "generation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_generation_logs_topic_id", "generation_logs", ["topic_id"])

def downgrade():
    op.drop_index("ix_generation_logs_topic_id", table_name="generation_logs")
    op.drop_table("generation_logs")
    op.drop_index("ix_topic_embeddings_topic_id", table_name="topic_embeddings")
    op.drop_table("topic_embeddings")

