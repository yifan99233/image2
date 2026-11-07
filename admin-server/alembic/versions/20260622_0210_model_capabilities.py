"""model capabilities

Revision ID: 20260622_0210
Revises: 20260619_1830
Create Date: 2026-06-22 02:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0210"
down_revision: str | None = "20260619_1830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("image_models", sa.Column("capability_type", sa.String(length=32), nullable=False, server_default="image"))
    op.add_column("image_models", sa.Column("supports_image_edit", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        """
        UPDATE image_models
        SET
            capability_type = CASE
                WHEN work_type IN ('text', 'text_generation') THEN 'text'
                WHEN work_type IN ('multimodal', 'vision_language') THEN 'multimodal'
                ELSE 'image'
            END,
            supports_image_edit = CASE
                WHEN work_type IN ('image_edit', 'batch_edit') THEN true
                ELSE false
            END
        """
    )


def downgrade() -> None:
    op.drop_column("image_models", "supports_image_edit")
    op.drop_column("image_models", "capability_type")
