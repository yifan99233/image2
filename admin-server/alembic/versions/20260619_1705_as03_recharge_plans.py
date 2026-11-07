"""AS-03 recharge plans

Revision ID: 20260619_1705
Revises: 20260619_1455
Create Date: 2026-06-19 17:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_1705"
down_revision: str | None = "20260619_1455"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recharge_plans",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("credit_amount", sa.Integer(), nullable=False),
        sa.Column("bonus_credit_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("badge", sa.String(length=32), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("is_recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_recharge_plans_active_sort", "recharge_plans", ["is_active", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_recharge_plans_active_sort", table_name="recharge_plans")
    op.drop_table("recharge_plans")
