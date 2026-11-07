"""add site icon url

Revision ID: 20260729_0200
Revises: 20260729_0100
Create Date: 2026-07-29 00:00:00
"""

from alembic import op


revision = "20260729_0200"
down_revision = "20260729_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE site_configs "
        "ADD COLUMN IF NOT EXISTS site_icon_url TEXT NOT NULL DEFAULT '/image2ai-icon.svg'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE site_configs DROP COLUMN IF EXISTS site_icon_url")
