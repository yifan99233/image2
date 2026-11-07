"""add provider trace fields to image tasks

Revision ID: 20260710_0400
Revises: 20260708_0310
Create Date: 2026-07-10 04:00:00
"""

from alembic import op


revision = "20260710_0400"
down_revision = "20260708_0310"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS provider_request_id VARCHAR(128)")
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS provider_request_snapshot TEXT")
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS provider_response_summary TEXT")
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS provider_http_status INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_tasks_provider_request_id ON image_tasks (provider_request_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_image_tasks_provider_request_id")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS provider_http_status")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS provider_response_summary")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS provider_request_snapshot")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS provider_request_id")
