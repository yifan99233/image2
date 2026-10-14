"""system super admin permission

Revision ID: 20260705_0100
Revises: 20260704_0420
Create Date: 2026-07-05 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260705_0100"
down_revision: str | None = "20260704_0420"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS system_super_admin BOOLEAN NOT NULL DEFAULT false")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_users_system_super_admin ON admin_users (system_super_admin)")
    op.execute("UPDATE admin_users SET system_super_admin = false WHERE username = 'admin'")
    op.execute("UPDATE admin_users SET system_super_admin = true WHERE username = 'yifan'")


def downgrade() -> None:
    op.drop_index("ix_admin_users_system_super_admin", table_name="admin_users")
    op.drop_column("admin_users", "system_super_admin")
