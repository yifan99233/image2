"""add user image concurrency limit

Revision ID: 20260705_0540
Revises: 20260705_0530
Create Date: 2026-07-05 05:40:00.000000
"""

from alembic import op


revision = "20260705_0540"
down_revision = "20260705_0530"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS image_concurrency_limit INTEGER NOT NULL DEFAULT 1")
    op.execute("UPDATE users SET image_concurrency_limit = 1 WHERE image_concurrency_limit IS NULL OR image_concurrency_limit < 1")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS image_concurrency_limit")
