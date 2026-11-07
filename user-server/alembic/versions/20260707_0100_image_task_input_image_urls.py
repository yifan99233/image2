"""add multiple input image urls to image tasks

Revision ID: 20260707_0100
Revises: 20260706_0240
Create Date: 2026-07-07 00:00:00.000000
"""

from alembic import op


revision = "20260707_0100"
down_revision = "20260706_0240"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS image_tasks ADD COLUMN IF NOT EXISTS input_image_urls TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS image_tasks DROP COLUMN IF EXISTS input_image_urls")
