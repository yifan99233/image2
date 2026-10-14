"""add first-party image gateway api keys"""

from alembic import op


revision = "20260724_0100"
down_revision = "20260721_0500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE gateway_api_keys (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(120) NOT NULL,
            key_prefix VARCHAR(24) NOT NULL,
            key_hash VARCHAR(64) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            request_count BIGINT NOT NULL DEFAULT 0,
            last_used_at TIMESTAMPTZ,
            last_used_ip VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at TIMESTAMPTZ,
            CONSTRAINT uq_gateway_api_keys_key_hash UNIQUE (key_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_gateway_api_keys_site_user_active "
        "ON gateway_api_keys(site_id, user_id, is_active)"
    )
    op.execute("CREATE INDEX ix_gateway_api_keys_prefix ON gateway_api_keys(key_prefix)")
    op.execute("CREATE INDEX ix_gateway_api_keys_site_id ON gateway_api_keys(site_id)")
    op.execute("CREATE INDEX ix_gateway_api_keys_user_id ON gateway_api_keys(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE gateway_api_keys")
