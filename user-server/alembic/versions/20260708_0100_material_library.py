"""add user material library

Revision ID: 20260708_0100
Revises: 20260707_0100
Create Date: 2026-07-08 13:30:00
"""

from alembic import op

revision = "20260708_0100"
down_revision = "20260707_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_material_folders (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            user_id BIGINT NOT NULL REFERENCES users(id),
            parent_id BIGINT REFERENCES user_material_folders(id) ON DELETE CASCADE,
            name VARCHAR(120) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_material_folders_site_user_parent ON user_material_folders (site_id, user_id, parent_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_material_assets (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            user_id BIGINT NOT NULL REFERENCES users(id),
            folder_id BIGINT REFERENCES user_material_folders(id) ON DELETE SET NULL,
            image_asset_id BIGINT NOT NULL REFERENCES image_assets(id),
            name VARCHAR(160) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_material_assets_site_user_folder ON user_material_assets (site_id, user_id, folder_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_material_assets_image_asset ON user_material_assets (image_asset_id)")


def downgrade() -> None:
    op.drop_index("ix_user_material_assets_image_asset", table_name="user_material_assets")
    op.drop_index("ix_user_material_assets_site_user_folder", table_name="user_material_assets")
    op.drop_table("user_material_assets")
    op.drop_index("ix_user_material_folders_site_user_parent", table_name="user_material_folders")
    op.drop_table("user_material_folders")
