"""credit ledger abnormal flags

Revision ID: 20260622_0335
Revises: 20260622_0225
Create Date: 2026-06-22 03:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0335"
down_revision: str | None = "20260622_0225"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credit_ledger", sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("credit_ledger", sa.Column("flag_reason", sa.Text(), nullable=True))
    op.add_column("credit_ledger", sa.Column("flagged_by", sa.BigInteger(), nullable=True))
    op.add_column("credit_ledger", sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_credit_ledger_flagged", "credit_ledger", ["is_flagged"])


def downgrade() -> None:
    op.drop_index("idx_credit_ledger_flagged", table_name="credit_ledger")
    op.drop_column("credit_ledger", "flagged_at")
    op.drop_column("credit_ledger", "flagged_by")
    op.drop_column("credit_ledger", "flag_reason")
    op.drop_column("credit_ledger", "is_flagged")
