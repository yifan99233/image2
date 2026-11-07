"""add one-time user impersonation grants

Revision ID: 20260728_0100
Revises: 20260724_0100
Create Date: 2026-07-28 00:00:00
"""

from alembic import op


revision = "20260728_0100"
down_revision = "20260724_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_impersonation_grants (
            token_hash VARCHAR(64) PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            site_id BIGINT NOT NULL,
            admin_id BIGINT NOT NULL,
            admin_username VARCHAR(80) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_user_impersonation_grants_user_id ON user_impersonation_grants(user_id)")
    op.execute("CREATE INDEX ix_user_impersonation_grants_site_id ON user_impersonation_grants(site_id)")
    op.execute("CREATE INDEX ix_user_impersonation_grants_expires_at ON user_impersonation_grants(expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE user_impersonation_grants")
