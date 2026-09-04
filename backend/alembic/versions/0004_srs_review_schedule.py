"""Add SM-2 review schedules."""
from alembic import op
import sqlalchemy as sa

revision = "0004_srs_review_schedule"
down_revision = "0003_rag_pipeline"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "review_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ease_factor", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repetition_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_review_schedules_user_id", "review_schedules", ["user_id"])
    op.create_index("ix_review_schedules_topic_id", "review_schedules", ["topic_id"])

def downgrade():
    op.drop_index("ix_review_schedules_topic_id", table_name="review_schedules")
    op.drop_index("ix_review_schedules_user_id", table_name="review_schedules")
    op.drop_table("review_schedules")

