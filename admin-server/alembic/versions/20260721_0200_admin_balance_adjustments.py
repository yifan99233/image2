"""add durable admin balance adjustments

Revision ID: 20260721_0200
Revises: 20260721_0100
Create Date: 2026-07-21 15:30:00
"""

from alembic import op


revision = "20260721_0200"
down_revision = "20260721_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_balance_adjustments (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            admin_id BIGINT,
            agent_user_id BIGINT,
            delta INTEGER NOT NULL,
            agent_amount NUMERIC(18, 4) NOT NULL DEFAULT 0,
            credit_to_agent_rate NUMERIC(18, 4) NOT NULL DEFAULT 1,
            remote_balance NUMERIC(18, 4),
            balance_before INTEGER,
            balance_after INTEGER,
            reason VARCHAR(255) NOT NULL,
            idempotency_key VARCHAR(160) NOT NULL UNIQUE,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            failure_message VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_admin_balance_adjustments_delta_nonzero CHECK (delta <> 0),
            CONSTRAINT ck_admin_balance_adjustments_agent_amount_nonnegative CHECK (agent_amount >= 0),
            CONSTRAINT ck_admin_balance_adjustments_rate_positive CHECK (credit_to_agent_rate > 0),
            CONSTRAINT ck_admin_balance_adjustments_status
                CHECK (status IN ('pending', 'remote_applied', 'completed'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_admin_balance_adjustments_user_created
        ON admin_balance_adjustments(user_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_admin_balance_adjustments_status
        ON admin_balance_adjustments(status)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_balance_adjustments")
