"""add team member usage limit audit mirror

Revision ID: 20260721_0400
Revises: 20260721_0300
Create Date: 2026-07-21 16:00:00
"""

from alembic import op


revision = "20260721_0400"
down_revision = "20260721_0300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS team_member_usage_limits (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL,
            team_id BIGINT NOT NULL REFERENCES user_teams(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            text_quota NUMERIC(18, 4) NOT NULL DEFAULT 0,
            image_quota NUMERIC(18, 4) NOT NULL DEFAULT 0,
            updated_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_team_member_usage_limits_team_user UNIQUE (team_id, user_id),
            CONSTRAINT ck_team_member_usage_limits_text_nonnegative CHECK (text_quota >= 0),
            CONSTRAINT ck_team_member_usage_limits_image_nonnegative CHECK (image_quota >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_team_member_usage_limits_site_team "
        "ON team_member_usage_limits (site_id, team_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_team_member_usage_limits_user_id "
        "ON team_member_usage_limits (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS team_member_usage_limits")
