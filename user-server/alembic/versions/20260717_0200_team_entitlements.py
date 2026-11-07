"""add team seat entitlements to recharge and admin grants

Revision ID: 20260717_0200
Revises: 20260717_0100
Create Date: 2026-07-17 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0200"
down_revision: str | None = "20260717_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE recharge_plans ADD COLUMN IF NOT EXISTS team_seat_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE recharge_plans ADD COLUMN IF NOT EXISTS team_duration_days INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE recharge_orders ADD COLUMN IF NOT EXISTS team_seat_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE recharge_orders ADD COLUMN IF NOT EXISTS team_duration_days INTEGER NOT NULL DEFAULT 0")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS team_entitlements (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            seat_count INTEGER NOT NULL,
            source VARCHAR(32) NOT NULL,
            source_reference VARCHAR(128) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'active',
            starts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NULL,
            note VARCHAR(255) NOT NULL DEFAULT '',
            created_by_admin_id BIGINT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_team_entitlements_seat_count_positive CHECK (seat_count > 0),
            CONSTRAINT uq_team_entitlements_source UNIQUE (site_id, source, source_reference)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_team_entitlements_owner_active "
        "ON team_entitlements (site_id, owner_user_id, status, expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_team_entitlements_owner_active")
    op.execute("DROP TABLE IF EXISTS team_entitlements")
    op.execute("ALTER TABLE recharge_orders DROP COLUMN IF EXISTS team_duration_days")
    op.execute("ALTER TABLE recharge_orders DROP COLUMN IF EXISTS team_seat_count")
    op.execute("ALTER TABLE recharge_plans DROP COLUMN IF EXISTS team_duration_days")
    op.execute("ALTER TABLE recharge_plans DROP COLUMN IF EXISTS team_seat_count")
