"""Durable batch-file intake and billing recovery journal."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_0100"
down_revision = "20261006_0200"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "image_batch_uploads",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("site_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger()),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("task_count", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("billing", postgresql.JSONB()),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("recovery_phase", sa.String(24)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "user_id", "batch_id", name="uq_image_batch_upload_owner_batch"),
    )
    op.create_index("idx_image_batch_upload_work", "image_batch_uploads", ["status", "next_attempt_at"])
    op.create_index("idx_image_batch_upload_user_status", "image_batch_uploads", ["user_id", "status"])
    op.create_index("idx_image_batch_upload_owner_created", "image_batch_uploads", ["site_id", "user_id", "created_at"])


def downgrade():
    op.drop_table("image_batch_uploads")
