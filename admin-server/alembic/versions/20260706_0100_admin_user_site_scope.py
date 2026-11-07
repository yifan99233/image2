"""admin user site scope

Revision ID: 20260706_0100
Revises: 20260705_0540
Create Date: 2026-07-06 01:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260706_0100"
down_revision: str | None = "20260705_0540"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS site_id BIGINT NOT NULL DEFAULT 1")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_users_site_id ON admin_users (site_id)")
    op.execute("UPDATE admin_users SET site_id = 1 WHERE site_id IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_admin_users_site_id")
    op.execute("ALTER TABLE admin_users DROP COLUMN IF EXISTS site_id")
