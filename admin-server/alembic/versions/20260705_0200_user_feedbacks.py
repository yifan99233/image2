"""user feedbacks

Revision ID: 20260705_0200
Revises: 20260705_0100
Create Date: 2026-07-05 02:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision = "20260705_0200"
down_revision = "20260705_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_feedbacks (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            description TEXT NOT NULL,
            image_urls TEXT NOT NULL DEFAULT '[]',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            admin_remark TEXT NOT NULL DEFAULT '',
            handled_by BIGINT,
            handled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_feedbacks_user_created ON user_feedbacks (user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_feedbacks_status_created ON user_feedbacks (status, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_feedbacks_status_created")
    op.execute("DROP INDEX IF EXISTS ix_user_feedbacks_user_created")
    op.execute("DROP TABLE IF EXISTS user_feedbacks")
