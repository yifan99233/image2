"""Persist retry lineage and enforce one child per failed attempt."""
from alembic import op
import sqlalchemy as sa

revision = "20261006_0200"
down_revision = "20261006_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("image_tasks", sa.Column("retry_of_task_id", sa.BigInteger(), nullable=True))
    op.add_column("image_tasks", sa.Column("retry_of_batch_id", sa.String(64), nullable=True))
    op.create_foreign_key("fk_image_tasks_retry_of_task", "image_tasks", "image_tasks", ["retry_of_task_id"], ["id"], ondelete="SET NULL")
    op.create_index("uq_image_tasks_retry_of_task", "image_tasks", ["retry_of_task_id"], unique=True, postgresql_where=sa.text("retry_of_task_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_image_tasks_retry_of_task", table_name="image_tasks")
    op.drop_constraint("fk_image_tasks_retry_of_task", "image_tasks", type_="foreignkey")
    op.drop_column("image_tasks", "retry_of_batch_id")
    op.drop_column("image_tasks", "retry_of_task_id")
