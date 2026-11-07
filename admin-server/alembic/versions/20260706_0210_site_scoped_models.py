"""site scoped image models and prices

Revision ID: 20260706_0210
Revises: 20260706_0200
Create Date: 2026-07-06 02:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260706_0210"
down_revision: str | None = "20260706_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("image_model_providers", "image_models", "image_model_prices"):
        op.execute(f"ALTER TABLE IF EXISTS {table_name} ADD COLUMN IF NOT EXISTS site_id BIGINT NOT NULL DEFAULT 1")

    op.execute(
        """
        UPDATE image_model_prices price
        SET site_id = model.site_id
        FROM image_models model
        WHERE price.model_id = model.id
        """
    )

    op.execute("ALTER TABLE IF EXISTS image_model_providers DROP CONSTRAINT IF EXISTS uq_image_model_providers_code")
    op.execute("ALTER TABLE IF EXISTS image_models DROP CONSTRAINT IF EXISTS uq_image_models_code")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_image_model_providers_site_code'
                  AND conrelid = 'image_model_providers'::regclass
            ) THEN
                ALTER TABLE image_model_providers ADD CONSTRAINT uq_image_model_providers_site_code UNIQUE (site_id, code);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_image_models_site_code'
                  AND conrelid = 'image_models'::regclass
            ) THEN
                ALTER TABLE image_models ADD CONSTRAINT uq_image_models_site_code UNIQUE (site_id, code);
            END IF;
        END
        $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_model_providers_site_active ON image_model_providers (site_id, is_active)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_models_site_active_sort ON image_models (site_id, is_active, sort_order)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_models_site_public_active_sort ON image_models (site_id, is_public, is_active, sort_order)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_model_prices_site_model_active ON image_model_prices (site_id, model_id, is_active)")


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS image_model_providers DROP CONSTRAINT IF EXISTS uq_image_model_providers_site_code")
    op.execute("ALTER TABLE IF EXISTS image_models DROP CONSTRAINT IF EXISTS uq_image_models_site_code")
    op.execute("ALTER TABLE IF EXISTS image_model_providers ADD CONSTRAINT uq_image_model_providers_code UNIQUE (code)")
    op.execute("ALTER TABLE IF EXISTS image_models ADD CONSTRAINT uq_image_models_code UNIQUE (code)")
    op.execute("DROP INDEX IF EXISTS ix_image_model_prices_site_model_active")
    op.execute("DROP INDEX IF EXISTS ix_image_models_site_public_active_sort")
    op.execute("DROP INDEX IF EXISTS ix_image_models_site_active_sort")
    op.execute("DROP INDEX IF EXISTS ix_image_model_providers_site_active")
    for table_name in ("image_model_prices", "image_models", "image_model_providers"):
        op.execute(f"ALTER TABLE IF EXISTS {table_name} DROP COLUMN IF EXISTS site_id")
