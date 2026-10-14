"""image tasks and gallery selections

Revision ID: 20260622_0730
Revises: 20260622_0630
Create Date: 2026-06-22 07:30:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260622_0730"
down_revision: str | None = "20260622_0630"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("task_no", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("model_id", sa.BigInteger(), nullable=False),
        sa.Column("work_type", sa.String(length=64), nullable=False, server_default="image_edit"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("aspect_ratio", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("credit_cost", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("input_image_url", sa.String(length=1024), nullable=True),
        sa.Column("output_image_url", sa.String(length=1024), nullable=True),
        sa.Column("is_gallery_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gallery_title", sa.String(length=120), nullable=True),
        sa.Column("gallery_sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gallery_featured_by", sa.BigInteger(), nullable=True),
        sa.Column("gallery_featured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_image_tasks_user_id_users"),
        sa.UniqueConstraint("task_no", name="uq_image_tasks_task_no"),
    )
    op.create_index("idx_image_tasks_user_created", "image_tasks", ["user_id", "created_at"])
    op.create_index("idx_image_tasks_status_created", "image_tasks", ["status", "created_at"])
    op.create_index("idx_image_tasks_gallery", "image_tasks", ["is_gallery_featured", "gallery_sort_order", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_image_tasks_gallery", table_name="image_tasks")
    op.drop_index("idx_image_tasks_status_created", table_name="image_tasks")
    op.drop_index("idx_image_tasks_user_created", table_name="image_tasks")
    op.drop_table("image_tasks")
