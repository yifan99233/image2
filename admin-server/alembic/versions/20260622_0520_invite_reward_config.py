"""invite reward config

Revision ID: 20260622_0520
Revises: 20260622_0410
Create Date: 2026-06-22 05:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0520"
down_revision: str | None = "20260622_0410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invite_reward_configs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_user_reward_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recharge_reward_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_user_rule", sa.String(length=120), nullable=False, server_default="invited_user_first_paid_recharge"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        """
        INSERT INTO invite_reward_configs
            (id, is_enabled, valid_user_reward_credits, recharge_reward_percent, valid_user_rule)
        VALUES
            (1, false, 0, 0, 'invited_user_first_paid_recharge')
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("invite_reward_configs")
