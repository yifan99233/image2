"""Persist named reference-image groups on batch tasks."""
from alembic import op
import sqlalchemy as sa

revision = "20261006_0100"
down_revision = "20261002_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("image_tasks", sa.Column("input_group_id", sa.String(64), nullable=True))
    op.add_column("image_tasks", sa.Column("input_group_name", sa.String(255), nullable=True))
    op.add_column("image_tasks", sa.Column("input_group_path", sa.String(1024), nullable=True))
    op.add_column("image_tasks", sa.Column("batch_request_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("image_tasks", "batch_request_hash")
    op.drop_column("image_tasks", "input_group_path")
    op.drop_column("image_tasks", "input_group_name")
    op.drop_column("image_tasks", "input_group_id")
