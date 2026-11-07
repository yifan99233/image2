"""user experience configs

Revision ID: 20260712_0100
Revises: 20260710_0400
Create Date: 2026-07-12 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260712_0100"
down_revision: str | None = "20260710_0400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_experience_configs (
            id BIGINT PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            max_batch_tasks INTEGER NOT NULL DEFAULT 50,
            updated_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_user_experience_configs_site ON user_experience_configs (site_id)")
    op.execute(
        """
        INSERT INTO user_experience_configs (id, site_id, max_batch_tasks)
        VALUES (1, 1, 50)
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_user_experience_configs_site")
    op.execute("DROP TABLE IF EXISTS user_experience_configs")
