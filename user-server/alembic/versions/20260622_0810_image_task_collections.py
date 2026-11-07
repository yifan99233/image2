"""image task collection flag

Revision ID: 20260622_0810
Revises: 20260622_0730
Create Date: 2026-06-22 08:10:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260622_0810"
down_revision: str | None = "20260622_0730"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("image_tasks", sa.Column("is_collected", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("image_tasks", "is_collected")
