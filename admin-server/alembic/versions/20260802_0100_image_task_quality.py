"""image task quality

Revision ID: 20260802_0100
Revises: 20260729_0200
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260802_0100"
down_revision: str | None = "20260729_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE image_tasks
        ADD COLUMN IF NOT EXISTS quality VARCHAR(16) NOT NULL DEFAULT 'auto'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE image_tasks DROP COLUMN IF EXISTS quality")
