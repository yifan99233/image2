"""site scoped agent configs

Revision ID: 20260706_0230
Revises: 20260706_0220
Create Date: 2026-07-06 02:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260706_0230"
down_revision: str | None = "20260706_0220"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS agent_configs ADD COLUMN IF NOT EXISTS site_id BIGINT NOT NULL DEFAULT 1")
    op.execute("UPDATE agent_configs SET site_id = 1 WHERE site_id IS NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_configs_site_id ON agent_configs (site_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_agent_configs_site_id")
    op.execute("ALTER TABLE IF EXISTS agent_configs DROP COLUMN IF EXISTS site_id")
