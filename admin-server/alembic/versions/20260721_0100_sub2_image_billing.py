"""add Sub2API image billing switch

Revision ID: 20260721_0100
Revises: 20260719_0100
Create Date: 2026-07-21 11:30:00
"""

from alembic import op


revision = "20260721_0100"
down_revision = "20260719_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_configs
        ADD COLUMN IF NOT EXISTS image_billing_enabled BOOLEAN NOT NULL DEFAULT false
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_configs DROP COLUMN IF EXISTS image_billing_enabled")
