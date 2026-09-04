"""Add user tracking and question quality metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0002_problem_bank"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("target_exam_date", sa.Date(), nullable=True))
        op.execute("INSERT INTO users (id, name) VALUES (1, '기본 사용자')")
    else:
        existing_users = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM users")).scalar()
        if not existing_users:
            op.execute("INSERT INTO users (id, name) VALUES (1, '기본 사용자')")

    question_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("questions")}
    if "quality_score" not in question_columns:
        op.add_column("questions", sa.Column("quality_score", sa.Float(), nullable=False, server_default="1.0"))
    if "generated_at" not in question_columns:
        op.add_column("questions", sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    if "model_version" not in question_columns:
        op.add_column("questions", sa.Column("model_version", sa.String(80), nullable=False, server_default="mock-v1"))

    answer_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("user_answer_logs")}
    if "user_id" not in answer_columns:
        op.add_column("user_answer_logs", sa.Column("user_id", sa.Integer(), nullable=True))
        op.execute("UPDATE user_answer_logs SET user_id = 1 WHERE user_id IS NULL")
        with op.batch_alter_table("user_answer_logs") as batch:
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
    if "time_spent" not in answer_columns:
        op.add_column("user_answer_logs", sa.Column("time_spent", sa.Integer(), nullable=True))

def downgrade():
    op.drop_column("user_answer_logs", "time_spent")
    op.drop_column("user_answer_logs", "user_id")
    op.drop_column("questions", "model_version")
    op.drop_column("questions", "generated_at")
    op.drop_column("questions", "quality_score")
    op.drop_table("users")

