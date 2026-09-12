"""Allow source documents that cover every subject (nullable subject_id)."""
from alembic import op
import sqlalchemy as sa

revision = "0009_documents_all_subjects"
down_revision = "0008_question_verification"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("source_documents") as batch:
        batch.alter_column("subject_id", existing_type=sa.Integer(), nullable=True)

def downgrade():
    with op.batch_alter_table("source_documents") as batch:
        batch.alter_column("subject_id", existing_type=sa.Integer(), nullable=False)
