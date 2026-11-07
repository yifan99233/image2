"""create image assets table

Revision ID: 20260619_1600
Revises: 20260619_1456
Create Date: 2026-06-19 16:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260619_1600"
down_revision = "20260619_1456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="upload"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_image_assets_user_id_users"),
        sa.UniqueConstraint("storage_key", name="uq_image_assets_storage_key"),
    )
    op.create_index("idx_image_assets_user_created", "image_assets", ["user_id", "created_at"])
    op.create_index("idx_image_assets_sha256", "image_assets", ["sha256"])


def downgrade() -> None:
    op.drop_index("idx_image_assets_sha256", table_name="image_assets")
    op.drop_index("idx_image_assets_user_created", table_name="image_assets")
    op.drop_table("image_assets")
