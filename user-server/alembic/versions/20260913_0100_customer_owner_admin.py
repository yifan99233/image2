"""add customer owner admin to users

Revision ID: 20260913_0100
Revises: 20260806_0100
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0100"
down_revision: str | None = "20260806_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS customer_owner_admin_id BIGINT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_site_customer_owner_admin "
        "ON users (site_id, customer_owner_admin_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_site_customer_owner_admin")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS customer_owner_admin_id")
