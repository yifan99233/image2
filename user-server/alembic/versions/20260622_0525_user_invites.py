"""user invites

Revision ID: 20260622_0525
Revises: 20260619_1610
Create Date: 2026-06-22 05:25:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20260622_0525"
down_revision = "20260619_1610"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("invited_by_user_id", sa.BigInteger(), nullable=True))
    op.create_index("idx_users_invited_by", "users", ["invited_by_user_id"])


def downgrade() -> None:
    op.drop_index("idx_users_invited_by", table_name="users")
    op.drop_column("users", "invited_by_user_id")
