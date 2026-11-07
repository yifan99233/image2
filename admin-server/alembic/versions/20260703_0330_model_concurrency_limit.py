"""add image model concurrency limit

Revision ID: 20260703_0330
Revises: 20260623_0110
Create Date: 2026-07-03 03:30:00.000000
"""

from alembic import op


revision = "20260703_0330"
down_revision = "20260623_0110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE image_models ADD COLUMN IF NOT EXISTS concurrency_limit INTEGER NOT NULL DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE image_models DROP COLUMN IF EXISTS concurrency_limit")
