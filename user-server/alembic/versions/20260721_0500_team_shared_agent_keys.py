"""share one agent wallet per team and track multiple member keys"""

from alembic import op


revision = "20260721_0500"
down_revision = "20260721_0400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_agent_accounts ADD COLUMN IF NOT EXISTS team_id BIGINT REFERENCES user_teams(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE user_agent_accounts ADD COLUMN IF NOT EXISTS agent_password VARCHAR(255)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_agent_accounts_team_id ON user_agent_accounts(team_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_agent_api_keys (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL,
            team_id BIGINT NOT NULL REFERENCES user_teams(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            agent_user_id BIGINT NOT NULL,
            agent_key_id BIGINT NOT NULL,
            api_key VARCHAR(1024) NOT NULL,
            name VARCHAR(255) NOT NULL DEFAULT '',
            group_id BIGINT,
            is_deleted BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_agent_api_keys_agent_key UNIQUE (agent_user_id, agent_key_id),
            CONSTRAINT uq_user_agent_api_keys_team_user_key UNIQUE (team_id, user_id, agent_key_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_agent_api_keys_team_user ON user_agent_api_keys(team_id, user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_agent_api_keys_agent_user ON user_agent_api_keys(agent_user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_agent_api_keys")
    op.execute("ALTER TABLE user_agent_accounts DROP COLUMN IF EXISTS agent_password")
    op.execute("ALTER TABLE user_agent_accounts DROP COLUMN IF EXISTS team_id")
