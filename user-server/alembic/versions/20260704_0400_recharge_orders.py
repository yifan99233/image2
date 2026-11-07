"""create recharge orders

Revision ID: 20260704_0400
Revises: 20260704_0220
Create Date: 2026-07-04 04:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0400"
down_revision: str | None = "20260704_0220"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recharge_orders",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("order_no", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("credit_amount", sa.Integer(), nullable=False),
        sa.Column("bonus_credit_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("payment_provider", sa.String(length=32), nullable=False, server_default="zpay"),
        sa.Column("payment_type", sa.String(length=32), nullable=False, server_default="alipay"),
        sa.Column("payment_trade_no", sa.String(length=128), nullable=True),
        sa.Column("pay_url", sa.Text(), nullable=True),
        sa.Column("qr_code", sa.Text(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("order_no", name="uq_recharge_orders_order_no"),
    )
    op.create_index("ix_recharge_orders_user_created", "recharge_orders", ["user_id", "created_at"])
    op.create_index("ix_recharge_orders_status_expires", "recharge_orders", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_recharge_orders_status_expires", table_name="recharge_orders")
    op.drop_index("ix_recharge_orders_user_created", table_name="recharge_orders")
    op.drop_table("recharge_orders")
