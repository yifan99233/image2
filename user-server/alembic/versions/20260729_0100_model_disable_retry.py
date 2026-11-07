"""add model-level retry policy and task snapshot

Revision ID: 20260729_0100
Revises: 20260728_0100
Create Date: 2026-07-29 00:00:00
"""

from alembic import op


revision = "20260729_0100"
down_revision = "20260728_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE image_models "
        "ADD COLUMN IF NOT EXISTS disable_retry BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE image_tasks "
        "ADD COLUMN IF NOT EXISTS disable_retry BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        """
        UPDATE image_tasks AS task
        SET disable_retry = model.disable_retry
        FROM image_models AS model
        WHERE task.model_id = model.id
          AND task.status IN ('pending', 'queued', 'running')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS disable_retry")
    op.execute("ALTER TABLE image_models DROP COLUMN IF EXISTS disable_retry")
