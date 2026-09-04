"""Add practical essay questions and answer history."""
from alembic import op
import sqlalchemy as sa

revision = "0005_essay_questions"
down_revision = "0004_srs_review_schedule"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("questions") as batch:
        batch.alter_column("choices", existing_type=sa.JSON(), nullable=True)
        batch.alter_column("answer_index", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("explanation", existing_type=sa.Text(), nullable=True)
        batch.add_column(sa.Column("model_answer", sa.Text(), nullable=True))
        batch.add_column(sa.Column("grading_keywords", sa.JSON(), nullable=True))
    op.create_table(
        "user_essay_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("ai_feedback", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_essay_answers_user_id", "user_essay_answers", ["user_id"])
    op.create_index("ix_user_essay_answers_question_id", "user_essay_answers", ["question_id"])

def downgrade():
    op.drop_index("ix_user_essay_answers_question_id", table_name="user_essay_answers")
    op.drop_index("ix_user_essay_answers_user_id", table_name="user_essay_answers")
    op.drop_table("user_essay_answers")
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("grading_keywords")
        batch.drop_column("model_answer")

