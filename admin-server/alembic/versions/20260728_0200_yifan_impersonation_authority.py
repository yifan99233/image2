"""ensure yifan retains system super-admin authority

Revision ID: 20260728_0200
Revises: 20260721_0200
Create Date: 2026-07-28 00:00:00
"""

from alembic import op


revision = "20260728_0200"
down_revision = "20260721_0200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE admin_users
        SET role = 'super_admin', system_super_admin = true
        WHERE lower(username) = 'yifan'
        """
    )


def downgrade() -> None:
    # The previous role/flag cannot be reconstructed safely.
    pass
