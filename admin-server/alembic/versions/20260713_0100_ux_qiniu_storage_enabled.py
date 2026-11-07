"""user experience qiniu storage enabled

Revision ID: 20260713_0100
Revises: 20260712_0100
Create Date: 2026-07-13 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260713_0100"
down_revision: str | None = "20260712_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_experience_configs
        ADD COLUMN IF NOT EXISTS qiniu_storage_enabled BOOLEAN NOT NULL DEFAULT false
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_experience_configs DROP COLUMN IF EXISTS qiniu_storage_enabled")
