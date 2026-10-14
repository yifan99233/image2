"""site configs

Revision ID: 20260704_0420
Revises: 20260704_0410
Create Date: 2026-07-04 04:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision = "20260704_0420"
down_revision = "20260704_0410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS site_configs (
            id BIGINT PRIMARY KEY,
            site_name VARCHAR(128) NOT NULL DEFAULT '艺源',
            support_qq VARCHAR(64) NOT NULL DEFAULT '',
            support_wechat VARCHAR(128) NOT NULL DEFAULT '',
            support_wechat_qrcode_url TEXT NOT NULL DEFAULT '',
            support_email VARCHAR(255) NOT NULL DEFAULT '',
            updated_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS site_configs")
