"""credit ledger for admin adjustments

Revision ID: 20260622_0225
Revises: 20260622_0210
Create Date: 2026-06-22 02:25:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0225"
down_revision: str | None = "20260622_0210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_before", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("biz_type", sa.String(length=40), nullable=False),
        sa.Column("biz_id", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("operator_type", sa.String(length=20), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["user_credit_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_ledger_idempotency_key"),
    )
    op.create_index("idx_credit_ledger_user_created", "credit_ledger", ["user_id", "created_at"])
    op.create_index("idx_credit_ledger_biz", "credit_ledger", ["biz_type", "biz_id"])


def downgrade() -> None:
    op.drop_index("idx_credit_ledger_biz", table_name="credit_ledger")
    op.drop_index("idx_credit_ledger_user_created", table_name="credit_ledger")
    op.drop_table("credit_ledger")
