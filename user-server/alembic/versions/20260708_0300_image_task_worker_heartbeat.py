"""add image task worker heartbeat

Revision ID: 20260708_0300
Revises: 20260708_0200
Create Date: 2026-07-08 19:40:00
"""

from alembic import op

revision = "20260708_0300"
down_revision = "20260708_0200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS worker_started_at TIMESTAMPTZ")
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS worker_heartbeat_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_tasks_status_worker_heartbeat ON image_tasks (status, worker_heartbeat_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_image_tasks_status_worker_heartbeat")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS worker_heartbeat_at")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS worker_started_at")
