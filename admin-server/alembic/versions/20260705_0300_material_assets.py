"""material assets

Revision ID: 20260705_0300
Revises: 20260705_0200
Create Date: 2026-07-05 03:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision = "20260705_0300"
down_revision = "20260705_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS material_assets (
            id BIGSERIAL PRIMARY KEY,
            asset_type VARCHAR(32) NOT NULL DEFAULT 'video',
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            file_url TEXT NOT NULL,
            cover_url TEXT NOT NULL DEFAULT '',
            mime_type VARCHAR(128) NOT NULL DEFAULT '',
            file_size BIGINT NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 50,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by BIGINT,
            updated_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_material_assets_type_active ON material_assets (asset_type, is_active, sort_order)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_material_assets_type_active")
    op.execute("DROP TABLE IF EXISTS material_assets")
