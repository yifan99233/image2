"""site scoped user data

Revision ID: 20260706_0200
Revises: 20260705_0440
Create Date: 2026-07-06 02:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260706_0200"
down_revision: str | None = "20260705_0440"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("users", "image_assets", "image_tasks", "user_feedbacks", "lead_trial_applications", "recharge_orders"):
        op.execute(f"ALTER TABLE IF EXISTS {table_name} ADD COLUMN IF NOT EXISTS site_id BIGINT NOT NULL DEFAULT 1")

    op.execute("CREATE INDEX IF NOT EXISTS ix_users_site_active_created ON users (site_id, is_active, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_assets_site_user_created ON image_assets (site_id, user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_tasks_site_user_created ON image_tasks (site_id, user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_tasks_site_gallery ON image_tasks (site_id, is_gallery_featured, gallery_sort_order DESC, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_feedbacks_site_status_created ON user_feedbacks (site_id, status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_lead_trial_applications_site_status_created ON lead_trial_applications (site_id, status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_recharge_orders_site_status_created ON recharge_orders (site_id, status, created_at DESC)")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_users_email'
                  AND conrelid = 'users'::regclass
            ) THEN
                ALTER TABLE users DROP CONSTRAINT uq_users_email;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_users_site_email'
                  AND conrelid = 'users'::regclass
            ) THEN
                ALTER TABLE users ADD CONSTRAINT uq_users_site_email UNIQUE (site_id, email);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS users DROP CONSTRAINT IF EXISTS uq_users_site_email")
    op.execute("ALTER TABLE IF EXISTS users ADD CONSTRAINT uq_users_email UNIQUE (email)")
    op.execute("DROP INDEX IF EXISTS ix_recharge_orders_site_status_created")
    op.execute("DROP INDEX IF EXISTS ix_lead_trial_applications_site_status_created")
    op.execute("DROP INDEX IF EXISTS ix_user_feedbacks_site_status_created")
    op.execute("DROP INDEX IF EXISTS ix_image_tasks_site_gallery")
    op.execute("DROP INDEX IF EXISTS ix_image_tasks_site_user_created")
    op.execute("DROP INDEX IF EXISTS ix_image_assets_site_user_created")
    op.execute("DROP INDEX IF EXISTS ix_users_site_active_created")
    for table_name in ("recharge_orders", "lead_trial_applications", "user_feedbacks", "image_tasks", "image_assets", "users"):
        op.execute(f"ALTER TABLE IF EXISTS {table_name} DROP COLUMN IF EXISTS site_id")
