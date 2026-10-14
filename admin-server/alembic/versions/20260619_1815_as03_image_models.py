"""AS-03 image model providers and models

Revision ID: 20260619_1815
Revises: 20260619_1705
Create Date: 2026-06-19 18:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_1815"
down_revision: str | None = "20260619_1705"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_model_providers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False, server_default="bearer"),
        sa.Column("encrypted_api_key", sa.String(length=1024), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_image_model_providers_code"),
    )
    op.create_table(
        "image_models",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("vendor_model", sa.String(length=160), nullable=False),
        sa.Column("work_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_stable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("speed_hint", sa.String(length=80), nullable=True),
        sa.Column("risk_hint", sa.String(length=160), nullable=True),
        sa.Column("max_input_images", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_output_images", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["provider_id"], ["image_model_providers.id"]),
        sa.UniqueConstraint("code", name="uq_image_models_code"),
    )
    op.create_index("ix_image_models_active_sort", "image_models", ["is_active", "sort_order"])

    op.execute(
        """
        INSERT INTO image_model_providers
            (id, name, code, base_url, auth_type, encrypted_api_key, timeout_seconds, retry_count, is_active)
        VALUES
            (1, 'OpenAI', 'openai', 'https://api.openai.com/v1', 'bearer', 'sk-***', 30, 1, true)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO image_models
            (id, provider_id, name, code, vendor_model, work_type, description,
             is_recommended, is_stable, is_new, speed_hint, risk_hint,
             max_input_images, max_output_images, sort_order, is_active)
        VALUES
            (1, 1, 'GPT Image 1', 'gpt-image-1-edit', 'gpt-image-1', 'image_edit',
             '真实数据库中的默认图片编辑模型配置', true, true, true, '标准', null, 4, 1, 10, true)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_image_models_active_sort", table_name="image_models")
    op.drop_table("image_models")
    op.drop_table("image_model_providers")

