"""add active team selection and team membership indexes

Revision ID: 20260717_0100
Revises: 20260714_0100
Create Date: 2026-07-17 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0100"
down_revision: str | None = "20260714_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS active_team_id BIGINT REFERENCES user_teams(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_site_active_team ON users (site_id, active_team_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_team_members_team_role ON user_team_members (team_id, role, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_team_members_team_role")
    op.execute("DROP INDEX IF EXISTS ix_users_site_active_team")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS active_team_id")
