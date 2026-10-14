"""Exact hundredth-credit accounting and immutable task pricing."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261012_0100"
down_revision = "20261010_0100"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "user_credit_accounts": ("balance", "gift_balance", "total_gifted", "total_recharged", "total_consumed"),
    "credit_ledger": ("amount", "gift_amount", "balance_before", "balance_after"),
    "image_tasks": ("credit_cost",),
    "admin_balance_adjustments": ("balance_before", "balance_after"),
}


def upgrade():
    for table, columns in MONEY_COLUMNS.items():
        # The adjustment journal belongs to admin-server and may not exist yet
        # on a fresh user-server installation.
        if not sa.inspect(op.get_bind()).has_table(table):
            continue
        for column in columns:
            op.alter_column(table, column, type_=sa.Numeric(20, 2), postgresql_using=f'"{column}"::numeric(20,2)')
    op.add_column("image_tasks", sa.Column("pricing_snapshot", postgresql.JSONB()))


def downgrade():
    # Never silently round customer balances when rolling back this migration.
    bind = op.get_bind()
    for table, columns in MONEY_COLUMNS.items():
        if not sa.inspect(bind).has_table(table):
            continue
        for column in columns:
            if bind.scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table}" WHERE "{column}" <> trunc("{column}") OR abs("{column}") > 2147483647)')):
                raise RuntimeError("Fractional or large balances exist; accounting migration cannot be rolled back safely")
    op.drop_column("image_tasks", "pricing_snapshot")
    for table, columns in MONEY_COLUMNS.items():
        if sa.inspect(bind).has_table(table):
            for column in columns:
                op.alter_column(table, column, type_=sa.Integer(), postgresql_using=f'"{column}"::integer')
