"""Model surcharges and site-scoped customer VIP tiers."""
from alembic import op
import sqlalchemy as sa

revision = "20261012_0100"
down_revision = "20260924_0200"
branch_labels = None
depends_on = None


def upgrade():
    for column in ("balance_before", "balance_after"):
        op.alter_column("admin_balance_adjustments", column, type_=sa.Numeric(20, 2))
    op.add_column("image_model_prices", sa.Column("fixed_surcharge", sa.Numeric(20, 2), nullable=False, server_default="0"))
    op.create_check_constraint("ck_model_price_surcharge", "image_model_prices", "fixed_surcharge >= 0")
    op.create_table("customer_vip_tiers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("site_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("discount_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("discount_rate >= 0.01 AND discount_rate <= 1", name="ck_vip_discount_rate"),
        sa.UniqueConstraint("site_id", "name", name="uq_vip_tier_site_name"),
        sa.UniqueConstraint("site_id", "id", name="uq_vip_tier_site_id"))
    op.create_table("customer_vip_memberships",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("site_id", sa.BigInteger(), nullable=False),
        sa.Column("tier_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["site_id", "tier_id"], ["customer_vip_tiers.site_id", "customer_vip_tiers.id"]),
    )
    op.create_index("ix_vip_membership_site_tier", "customer_vip_memberships", ["site_id", "tier_id"])


def downgrade():
    op.drop_table("customer_vip_memberships")
    op.drop_table("customer_vip_tiers")
    op.drop_constraint("ck_model_price_surcharge", "image_model_prices")
    op.drop_column("image_model_prices", "fixed_surcharge")
