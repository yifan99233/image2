"""image specs and model supported specs

Revision ID: 20260622_0410
Revises: 20260622_0335
Create Date: 2026-06-22 04:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0410"
down_revision: str | None = "20260622_0335"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_resolution_specs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_image_resolution_specs_code"),
    )
    op.create_index("ix_image_resolution_specs_active_sort", "image_resolution_specs", ["is_active", "sort_order"])
    op.create_table(
        "image_aspect_ratio_specs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_image_aspect_ratio_specs_code"),
    )
    op.create_index("ix_image_aspect_ratio_specs_active_sort", "image_aspect_ratio_specs", ["is_active", "sort_order"])
    op.create_table(
        "image_model_resolutions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("model_id", sa.BigInteger(), nullable=False),
        sa.Column("resolution_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["model_id"], ["image_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolution_id"], ["image_resolution_specs.id"]),
        sa.UniqueConstraint("model_id", "resolution_id", name="uq_image_model_resolution"),
    )
    op.create_table(
        "image_model_aspect_ratios",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("model_id", sa.BigInteger(), nullable=False),
        sa.Column("aspect_ratio_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["model_id"], ["image_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["aspect_ratio_id"], ["image_aspect_ratio_specs.id"]),
        sa.UniqueConstraint("model_id", "aspect_ratio_id", name="uq_image_model_aspect_ratio"),
    )
    op.execute(
        """
        INSERT INTO image_resolution_specs (code, label, sort_order, is_active)
        VALUES
            ('720p', '720P', 10, true),
            ('1k', '1K', 20, true),
            ('2k', '2K', 30, true),
            ('4k', '4K', 40, true)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO image_aspect_ratio_specs (code, label, sort_order, is_active)
        VALUES
            ('1:1', '1:1', 10, true),
            ('4:3', '4:3', 20, true),
            ('3:4', '3:4', 30, true),
            ('16:9', '16:9', 40, true),
            ('9:16', '9:16', 50, true),
            ('3:2', '3:2', 60, true),
            ('2:3', '2:3', 70, true),
            ('21:9', '21:9', 80, true)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute("UPDATE image_model_prices SET resolution = '1k' WHERE resolution = '1024x1024'")
    op.execute(
        """
        INSERT INTO image_model_resolutions (model_id, resolution_id)
        SELECT model.id, spec.id
        FROM image_models model
        JOIN image_resolution_specs spec ON spec.code = '1k'
        WHERE model.id = 1
        ON CONFLICT (model_id, resolution_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO image_model_aspect_ratios (model_id, aspect_ratio_id)
        SELECT model.id, spec.id
        FROM image_models model
        JOIN image_aspect_ratio_specs spec ON spec.code = '1:1'
        WHERE model.id = 1
        ON CONFLICT (model_id, aspect_ratio_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("UPDATE image_model_prices SET resolution = '1024x1024' WHERE resolution = '1k'")
    op.drop_table("image_model_aspect_ratios")
    op.drop_table("image_model_resolutions")
    op.drop_index("ix_image_aspect_ratio_specs_active_sort", table_name="image_aspect_ratio_specs")
    op.drop_table("image_aspect_ratio_specs")
    op.drop_index("ix_image_resolution_specs_active_sort", table_name="image_resolution_specs")
    op.drop_table("image_resolution_specs")
