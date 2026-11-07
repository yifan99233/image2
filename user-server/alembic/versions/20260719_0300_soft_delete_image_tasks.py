"""soft delete image tasks

Revision ID: 20260719_0300
Revises: 20260719_0200
Create Date: 2026-07-19 03:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260719_0300"
down_revision: str | None = "20260719_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_image_tasks_site_user_deleted_created "
        "ON image_tasks (site_id, user_id, deleted_at, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_image_tasks_site_user_deleted_created")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS deleted_at")
