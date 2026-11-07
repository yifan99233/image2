"""model storage mode

Revision ID: 20260714_0100
Revises: 20260713_0200
Create Date: 2026-07-14 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260714_0100"
down_revision: str | None = "20260713_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE image_models
        ADD COLUMN IF NOT EXISTS storage_mode VARCHAR(32) NOT NULL DEFAULT 'local'
        """
    )
    op.execute(
        """
        UPDATE image_models
        SET storage_mode = 'local'
        WHERE storage_mode IS NULL OR storage_mode = ''
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE image_models DROP COLUMN IF EXISTS storage_mode")
