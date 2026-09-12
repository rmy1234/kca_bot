"""Add verification_status to questions."""
from alembic import op
import sqlalchemy as sa

revision = "0008_question_verification"
down_revision = "0007_user_auth"
branch_labels = None
depends_on = None

def upgrade():
    question_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("questions")}
    if "verification_status" not in question_columns:
        op.add_column("questions", sa.Column("verification_status", sa.String(20), nullable=False, server_default="verified"))

def downgrade():
    op.drop_column("questions", "verification_status")
