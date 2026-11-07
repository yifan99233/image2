"""Add gift credit accounting columns.

Revision ID: 20261002_0100
Revises: 20260916_0100
Create Date: 2026-10-02 21:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20261002_0100"
down_revision = "20260916_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_credit_accounts",
        sa.Column("gift_balance", sa.Integer(), nullable=False, server_default="0"),
        if_not_exists=True,
    )
    op.add_column(
        "user_credit_accounts",
        sa.Column("total_gifted", sa.BigInteger(), nullable=False, server_default="0"),
        if_not_exists=True,
    )
    op.add_column(
        "credit_ledger",
        sa.Column("gift_amount", sa.Integer(), nullable=False, server_default="0"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_column("credit_ledger", "gift_amount")
    op.drop_column("user_credit_accounts", "total_gifted")
    op.drop_column("user_credit_accounts", "gift_balance")
