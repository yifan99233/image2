"""video duration specs and model supports

Revision ID: 20260713_0200
Revises: 20260713_0100
Create Date: 2026-07-13 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0200"
down_revision: str | None = "20260713_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_duration_specs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("site_id", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "code", name="uq_video_duration_specs_site_code"),
    )
    op.create_index(
        "ix_video_duration_specs_site_active_sort",
        "video_duration_specs",
        ["site_id", "is_active", "sort_order"],
    )
    op.create_table(
        "image_model_durations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("model_id", sa.BigInteger(), nullable=False),
        sa.Column("duration_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["model_id"], ["image_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["duration_id"], ["video_duration_specs.id"]),
        sa.UniqueConstraint("model_id", "duration_id", name="uq_image_model_duration"),
    )
    op.execute(
        """
        INSERT INTO video_duration_specs (site_id, code, label, sort_order, is_active)
        SELECT sites.site_id, durations.code, durations.label, durations.sort_order, true
        FROM (
            SELECT DISTINCT site_id FROM image_resolution_specs
            UNION
            SELECT 1
        ) sites
        CROSS JOIN (
            VALUES
                ('6', '6 秒', 10),
                ('10', '10 秒', 20)
        ) AS durations(code, label, sort_order)
        WHERE NOT EXISTS (
            SELECT 1 FROM video_duration_specs existing
            WHERE existing.site_id = sites.site_id AND existing.code = durations.code
        )
        """
    )
    op.execute(
        """
        INSERT INTO image_resolution_specs (site_id, code, label, sort_order, is_active)
        SELECT sites.site_id, '480p', '480P', 5, true
        FROM (
            SELECT DISTINCT site_id FROM image_resolution_specs
            UNION
            SELECT 1
        ) sites
        WHERE NOT EXISTS (
            SELECT 1 FROM image_resolution_specs existing
            WHERE existing.site_id = sites.site_id AND existing.code = '480p'
        )
        """
    )


def downgrade() -> None:
    op.drop_table("image_model_durations")
    op.drop_index("ix_video_duration_specs_site_active_sort", table_name="video_duration_specs")
    op.drop_table("video_duration_specs")
