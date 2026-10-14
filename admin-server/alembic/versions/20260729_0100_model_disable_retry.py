"""add model-level retry policy

Revision ID: 20260729_0100
Revises: 20260728_0200
Create Date: 2026-07-29 00:00:00
"""

from alembic import op


revision = "20260729_0100"
down_revision = "20260728_0200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE image_models "
        "ADD COLUMN IF NOT EXISTS disable_retry BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE image_models DROP COLUMN IF EXISTS disable_retry")
