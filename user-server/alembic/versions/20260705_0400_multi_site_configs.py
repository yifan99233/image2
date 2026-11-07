"""add multi site config fields

Revision ID: 20260705_0400
Revises: 20260705_0310
Create Date: 2026-07-05 04:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260705_0400"
down_revision: str | None = "20260705_0310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS site_key VARCHAR(64) NOT NULL DEFAULT 'main'")
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS frontend_url TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS admin_url TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS enabled_modules TEXT NOT NULL DEFAULT ''")
    op.execute("UPDATE site_configs SET site_key = 'main', is_default = true WHERE id = 1")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_site_configs_site_key ON site_configs (site_key)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_site_configs_default ON site_configs (is_default) WHERE is_default")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_site_configs_default")
    op.execute("DROP INDEX IF EXISTS uq_site_configs_site_key")
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS enabled_modules")
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS is_enabled")
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS is_default")
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS admin_url")
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS frontend_url")
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS site_key")
