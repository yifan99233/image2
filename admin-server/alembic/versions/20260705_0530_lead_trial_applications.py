"""lead trial applications

Revision ID: 20260705_0530
Revises: 20260705_0520
Create Date: 2026-07-05 05:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision = "20260705_0530"
down_revision = "20260705_0520"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_trial_applications (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            business_scope TEXT NOT NULL,
            keywords TEXT NOT NULL,
            competitor_accounts TEXT NOT NULL DEFAULT '',
            contact_info VARCHAR(255) NOT NULL DEFAULT '',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            admin_remark TEXT NOT NULL DEFAULT '',
            handled_by_admin_id BIGINT,
            handled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_lead_trial_applications_user_created ON lead_trial_applications (user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_lead_trial_applications_status_created ON lead_trial_applications (status, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_lead_trial_applications_status_created")
    op.execute("DROP INDEX IF EXISTS ix_lead_trial_applications_user_created")
    op.execute("DROP TABLE IF EXISTS lead_trial_applications")
