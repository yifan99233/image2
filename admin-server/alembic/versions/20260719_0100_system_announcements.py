"""add system announcement configuration

Revision ID: 20260719_0100
Revises: 20260714_0100
Create Date: 2026-07-19 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260719_0100"
down_revision: str | None = "20260714_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS system_announcement TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS system_announcement")
