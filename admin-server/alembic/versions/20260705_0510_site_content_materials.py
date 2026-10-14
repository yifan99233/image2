"""add site content material fields

Revision ID: 20260705_0510
Revises: 20260705_0500
Create Date: 2026-07-05 05:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision = "20260705_0510"
down_revision = "20260705_0500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS lead_case_materials TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS opencode_install_video TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS opencode_install_video")
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS lead_case_materials")
