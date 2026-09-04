"""Create MVP curriculum and question tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("subjects", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False, unique=True), sa.Column("weight", sa.Integer(), nullable=False, server_default="20"))
    op.create_table("domains", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False), sa.Column("name", sa.String(160), nullable=False))
    op.create_index("ix_domains_subject_id", "domains", ["subject_id"])
    op.create_table("topics", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("summary_text", sa.Text(), nullable=False), sa.Column("keywords", sa.JSON(), nullable=False), sa.Column("difficulty_level", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_topics_domain_id", "topics", ["domain_id"])
    op.create_table("questions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False), sa.Column("exam_type", sa.String(30), nullable=False, server_default="written"), sa.Column("type", sa.String(30), nullable=False, server_default="multiple_choice"), sa.Column("question_text", sa.Text(), nullable=False), sa.Column("choices", sa.JSON(), nullable=False), sa.Column("answer_index", sa.Integer(), nullable=False), sa.Column("explanation", sa.Text(), nullable=False), sa.Column("source", sa.String(500)), sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_questions_topic_id", "questions", ["topic_id"])
    op.create_table("user_answer_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False), sa.Column("selected_index", sa.Integer(), nullable=False), sa.Column("is_correct", sa.Boolean(), nullable=False), sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_user_answer_logs_question_id", "user_answer_logs", ["question_id"])

def downgrade():
    op.drop_table("user_answer_logs")
    op.drop_table("questions")
    op.drop_table("topics")
    op.drop_table("domains")
    op.drop_table("subjects")

