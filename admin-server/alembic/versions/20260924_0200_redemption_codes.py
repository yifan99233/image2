"""Single-use gift credit redemption codes."""
from alembic import op
import sqlalchemy as sa

revision = "20260924_0200"
down_revision = "20260924_0100"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("redemption_batches", sa.Column("id", sa.String(36), primary_key=True), sa.Column("site_id", sa.BigInteger(), nullable=False), sa.Column("created_by", sa.BigInteger(), nullable=False), if_not_exists=True)
    op.add_column("user_credit_accounts", sa.Column("gift_balance", sa.Integer(), nullable=False, server_default="0"), if_not_exists=True)
    op.add_column("user_credit_accounts", sa.Column("total_gifted", sa.BigInteger(), nullable=False, server_default="0"), if_not_exists=True)
    op.add_column("credit_ledger", sa.Column("gift_amount", sa.Integer(), nullable=False, server_default="0"), if_not_exists=True)
    op.create_table(
        "redemption_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("site_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("code_hint", sa.String(12), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="unused"),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("redeemed_by", sa.BigInteger()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("redeemed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("agent_user_id", sa.BigInteger()),
        sa.Column("agent_base_url", sa.Text()),
        sa.Column("agent_amount", sa.Numeric(20, 4)),
        sa.CheckConstraint("amount > 0", name="ck_redemption_positive_amount"),
        sa.CheckConstraint("status IN ('unused', 'processing', 'redeemed', 'disabled')", name="ck_redemption_status"),
        if_not_exists=True,
    )
    op.create_index("ix_redemption_codes_site_created", "redemption_codes", ["site_id", "created_at"], if_not_exists=True)
    op.create_index("ix_redemption_codes_batch_id", "redemption_codes", ["batch_id"], if_not_exists=True)


def downgrade():
    op.drop_table("redemption_codes")
    op.drop_table("redemption_batches")
    op.drop_column("credit_ledger", "gift_amount")
    op.drop_column("user_credit_accounts", "total_gifted")
    op.drop_column("user_credit_accounts", "gift_balance")
