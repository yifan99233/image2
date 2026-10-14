"""add homepage batch banner carousel config

Revision ID: 20260705_0520
Revises: 20260705_0510
Create Date: 2026-07-05 05:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision = "20260705_0520"
down_revision = "20260705_0510"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS homepage_batch_banners TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS homepage_batch_banners")
