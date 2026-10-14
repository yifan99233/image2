"""move generation timeouts to individual models

Revision ID: 20260717_0300
Revises: 20260717_0200
Create Date: 2026-07-17 15:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0300"
down_revision: str | None = "20260717_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE image_models ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 120")
    op.execute(
        """
        UPDATE image_models AS model
        SET timeout_seconds = GREATEST(10, LEAST(COALESCE(provider.timeout_seconds, 120), 3600))
        FROM image_model_providers AS provider
        WHERE model.provider_id = provider.id
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_image_models_timeout_seconds_range'
            ) THEN
                ALTER TABLE image_models
                ADD CONSTRAINT ck_image_models_timeout_seconds_range
                CHECK (timeout_seconds BETWEEN 10 AND 3600);
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER")
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMPTZ")
    op.execute(
        """
        UPDATE image_tasks AS task
        SET timeout_seconds = model.timeout_seconds
        FROM image_models AS model
        WHERE task.model_id = model.id
          AND task.timeout_seconds IS NULL
        """
    )
    op.execute(
        "UPDATE image_tasks SET timeout_seconds = "
        "GREATEST(10, LEAST(COALESCE(timeout_seconds, 120), 3600))"
    )
    op.execute(
        """
        UPDATE image_tasks
        SET deadline_at = COALESCE(worker_started_at, created_at, now())
            + timeout_seconds * INTERVAL '1 second'
        WHERE status = 'running'
          AND deadline_at IS NULL
        """
    )
    op.execute("ALTER TABLE image_tasks ALTER COLUMN timeout_seconds SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_image_tasks_timeout_seconds_range'
            ) THEN
                ALTER TABLE image_tasks
                ADD CONSTRAINT ck_image_tasks_timeout_seconds_range
                CHECK (timeout_seconds BETWEEN 10 AND 3600);
            END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_tasks_running_deadline ON image_tasks (status, deadline_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_image_tasks_running_deadline")
    op.execute("ALTER TABLE image_tasks DROP CONSTRAINT IF EXISTS ck_image_tasks_timeout_seconds_range")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS deadline_at")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS timeout_seconds")
    op.execute("ALTER TABLE image_models DROP CONSTRAINT IF EXISTS ck_image_models_timeout_seconds_range")
    op.execute("ALTER TABLE image_models DROP COLUMN IF EXISTS timeout_seconds")
