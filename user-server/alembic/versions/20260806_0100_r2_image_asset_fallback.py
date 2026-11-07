"""add R2 hot URLs and local image fallbacks

Revision ID: 20260806_0100
Revises: 20260802_0100
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260806_0100"
down_revision: str | None = "20260802_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE image_assets ADD COLUMN IF NOT EXISTS local_url VARCHAR(1024)")
    op.execute("ALTER TABLE image_assets ADD COLUMN IF NOT EXISTS r2_url VARCHAR(1024)")
    op.execute("ALTER TABLE image_assets ADD COLUMN IF NOT EXISTS r2_expires_at TIMESTAMPTZ")
    op.execute("UPDATE image_assets SET local_url = url WHERE local_url IS NULL")

    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS output_image_r2_url VARCHAR(1024)")
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS output_image_r2_expires_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS output_image_r2_expires_at")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS output_image_r2_url")
    op.execute("ALTER TABLE image_assets DROP COLUMN IF EXISTS r2_expires_at")
    op.execute("ALTER TABLE image_assets DROP COLUMN IF EXISTS r2_url")
    op.execute("ALTER TABLE image_assets DROP COLUMN IF EXISTS local_url")
