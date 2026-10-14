"""model public visibility and internal users

Revision ID: 20260705_0300
Revises: 20260705_0200
Create Date: 2026-07-05 03:00:00.000000
"""

from alembic import op

revision = "20260705_0300"
down_revision = "20260705_0200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE image_models ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_models_public_active_sort ON image_models (is_public, is_active, sort_order)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_internal BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_internal_active ON users (is_internal, is_active)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_internal_active")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_internal")
    op.execute("DROP INDEX IF EXISTS ix_image_models_public_active_sort")
    op.execute("ALTER TABLE image_models DROP COLUMN IF EXISTS is_public")
