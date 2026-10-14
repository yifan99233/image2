"""persist image-task batch identifiers

Revision ID: 20260719_0200
Revises: 20260719_0100
Create Date: 2026-07-19 02:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260719_0200"
down_revision: str | None = "20260719_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS batch_id VARCHAR(64)")
    # Legacy rows made through /image-tasks/batch share a single transaction timestamp.
    # This is a persisted batch boundary, unlike prompt or time-window guessing.
    op.execute(
        """
        UPDATE image_tasks
        SET batch_id = 'legacy-' || substring(
            md5(concat_ws(':', site_id::text, user_id::text, coalesce(team_id, 0)::text, created_at::text)),
            1,
            24
        )
        WHERE batch_id IS NULL
          AND work_type IN ('batch_generate', 'batch_edit')
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_image_tasks_site_user_batch_created "
        "ON image_tasks (site_id, user_id, batch_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_image_tasks_site_user_batch_created")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS batch_id")
