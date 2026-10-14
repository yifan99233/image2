"""add user team sharing

Revision ID: 20260708_0200
Revises: 20260708_0100
Create Date: 2026-07-08 15:50:00
"""

from alembic import op

revision = "20260708_0200"
down_revision = "20260708_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_teams (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            owner_user_id BIGINT NOT NULL REFERENCES users(id),
            name VARCHAR(120) NOT NULL,
            material_library_shared BOOLEAN NOT NULL DEFAULT true,
            image_history_shared BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_teams_site_owner ON user_teams (site_id, owner_user_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_team_members (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            team_id BIGINT NOT NULL REFERENCES user_teams(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id),
            role VARCHAR(24) NOT NULL DEFAULT 'owner',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_team_members_team_user UNIQUE (team_id, user_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_team_members_site_user ON user_team_members (site_id, user_id)")
    op.execute("ALTER TABLE user_material_folders ADD COLUMN IF NOT EXISTS team_id BIGINT REFERENCES user_teams(id)")
    op.execute("ALTER TABLE user_material_assets ADD COLUMN IF NOT EXISTS team_id BIGINT REFERENCES user_teams(id)")
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS team_id BIGINT REFERENCES user_teams(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_material_folders_team_parent ON user_material_folders (site_id, team_id, parent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_material_assets_team_folder ON user_material_assets (site_id, team_id, folder_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_tasks_team_created ON image_tasks (site_id, team_id, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_image_tasks_team_created")
    op.execute("DROP INDEX IF EXISTS ix_user_material_assets_team_folder")
    op.execute("DROP INDEX IF EXISTS ix_user_material_folders_team_parent")
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS team_id")
    op.execute("ALTER TABLE user_material_assets DROP COLUMN IF EXISTS team_id")
    op.execute("ALTER TABLE user_material_folders DROP COLUMN IF EXISTS team_id")
    op.drop_table("user_team_members")
    op.drop_index("ix_user_teams_site_owner", table_name="user_teams")
    op.drop_table("user_teams")
