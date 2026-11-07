"""AS-03 model prices and admin audit logs

Revision ID: 20260619_1830
Revises: 20260619_1815
Create Date: 2026-06-19 18:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_1830"
down_revision: str | None = "20260619_1815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_model_prices",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("model_id", sa.BigInteger(), nullable=False),
        sa.Column("work_type", sa.String(length=80), nullable=False),
        sa.Column("resolution", sa.String(length=64), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=32), nullable=False),
        sa.Column("output_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("credit_cost", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["model_id"], ["image_models.id"]),
    )
    op.create_index(
        "ix_image_model_prices_model_active",
        "image_model_prices",
        ["model_id", "work_type", "resolution", "aspect_ratio", "output_count", "is_active"],
    )
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_username", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_audit_logs_created", "admin_audit_logs", ["created_at"])
    op.create_index("ix_admin_audit_logs_operator", "admin_audit_logs", ["admin_username"])
    op.execute(
        """
        INSERT INTO image_model_prices
            (model_id, work_type, resolution, aspect_ratio, output_count, credit_cost, version, is_active, change_reason)
        VALUES
            (1, 'image_edit', '1024x1024', '1:1', 1, 120, 1, true, '初始化默认图片编辑模型价格')
        """
    )
    op.execute(
        """
        INSERT INTO admin_audit_logs
            (admin_id, admin_username, action, resource_type, resource_id, reason)
        VALUES
            (null, 'system', 'seed', 'image_model_prices', '1', '初始化默认价格配置')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_operator", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_created", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
    op.drop_index("ix_image_model_prices_model_active", table_name="image_model_prices")
    op.drop_table("image_model_prices")
