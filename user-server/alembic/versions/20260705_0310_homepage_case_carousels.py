"""homepage case carousels config

Revision ID: 20260705_0310
Revises: 20260705_0300
Create Date: 2026-07-05 03:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260705_0310"
down_revision: str | None = "20260705_0300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE site_configs ADD COLUMN IF NOT EXISTS homepage_case_carousels TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS homepage_case_carousels")
