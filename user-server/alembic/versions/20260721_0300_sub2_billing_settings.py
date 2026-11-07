"""add Sub2API unified balance billing

Revision ID: 20260721_0300
Revises: 20260719_0300
Create Date: 2026-07-21 10:30:00
"""

from alembic import op


revision = "20260721_0300"
down_revision = "20260719_0300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_configs
        ADD COLUMN IF NOT EXISTS image_billing_enabled BOOLEAN NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sub2_balance_operations (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            agent_user_id BIGINT NOT NULL,
            operation VARCHAR(16) NOT NULL,
            amount NUMERIC(18, 4) NOT NULL,
            biz_type VARCHAR(40) NOT NULL,
            biz_id VARCHAR(120) NOT NULL,
            idempotency_key VARCHAR(160) NOT NULL,
            notes VARCHAR(255) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_sub2_balance_operations_idempotency_key UNIQUE (idempotency_key),
            CONSTRAINT ck_sub2_balance_operations_operation CHECK (operation IN ('add', 'subtract')),
            CONSTRAINT ck_sub2_balance_operations_amount_positive CHECK (amount > 0)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sub2_balance_operations_site_id ON sub2_balance_operations (site_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sub2_balance_operations_user_id ON sub2_balance_operations (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sub2_balance_operations_biz ON sub2_balance_operations (biz_type, biz_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sub2_balance_operations")
    op.execute("ALTER TABLE agent_configs DROP COLUMN IF EXISTS image_billing_enabled")
