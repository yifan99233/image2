"""payment configs

Revision ID: 20260704_0410
Revises: 20260704_0300
Create Date: 2026-07-04 04:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision = "20260704_0410"
down_revision = "20260704_0300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_configs (
            id BIGINT PRIMARY KEY,
            provider VARCHAR(32) NOT NULL UNIQUE,
            is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            pid VARCHAR(128),
            pkey TEXT,
            api_base TEXT,
            notify_url TEXT,
            return_url TEXT,
            payment_type VARCHAR(32) NOT NULL DEFAULT 'alipay',
            payment_mode VARCHAR(32) NOT NULL DEFAULT 'qrcode',
            timeout_seconds INTEGER NOT NULL DEFAULT 10,
            order_expire_minutes INTEGER NOT NULL DEFAULT 30,
            updated_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payment_configs")
