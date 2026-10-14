"""add user lead modules"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0200"
down_revision = "20260704_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_lead_modules",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("enterprise_id", sa.String(length=128), nullable=False),
        sa.Column("enterprise_account", sa.String(length=128), nullable=False),
        sa.Column("enterprise_password_secret", sa.String(length=255), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("opened_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_lead_modules_user_id"),
    )
    op.create_index("idx_user_lead_modules_user_id", "user_lead_modules", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_user_lead_modules_user_id", table_name="user_lead_modules")
    op.drop_table("user_lead_modules")
