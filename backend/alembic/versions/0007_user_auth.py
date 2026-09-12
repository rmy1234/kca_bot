"""Add auth fields (email, password_hash, is_admin) to users."""
from alembic import op
import sqlalchemy as sa

revision = "0007_user_auth"
down_revision = "0006_content_ingestion"
branch_labels = None
depends_on = None

def upgrade():
    user_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "email" not in user_columns:
        op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    if "password_hash" not in user_columns:
        op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    if "is_admin" not in user_columns:
        op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"))

def downgrade():
    op.drop_column("users", "is_admin")
    op.drop_column("users", "password_hash")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email")
