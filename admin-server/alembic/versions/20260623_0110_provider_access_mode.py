"""provider access mode

Revision ID: 20260623_0110
Revises: 20260622_0630
Create Date: 2026-06-23 01:10:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260623_0110"
down_revision: str | None = "20260622_0630"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("image_model_providers", sa.Column("access_mode", sa.String(length=32), nullable=False, server_default="api"))
    op.execute(
        """
        INSERT INTO image_model_providers
            (id, name, code, base_url, access_mode, auth_type, encrypted_api_key, timeout_seconds, retry_count, is_active)
        VALUES
            (31, 'Google 3.1 Image', 'google-3-1-image-sdk', 'http://127.0.0.1:8045/v1', 'sdk', 'bearer',
             null, 120, 1, true)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            base_url = EXCLUDED.base_url,
            access_mode = EXCLUDED.access_mode,
            auth_type = EXCLUDED.auth_type,
            timeout_seconds = EXCLUDED.timeout_seconds,
            is_active = true
        """
    )
    op.execute(
        """
        INSERT INTO image_models
            (id, provider_id, name, code, vendor_model, work_type, capability_type, supports_image_edit, description,
             is_recommended, is_stable, is_new, speed_hint, risk_hint, max_input_images, max_output_images, sort_order, is_active)
        VALUES
            (31, 31, '3.1 image', 'google-3-1-image', 'gemini-3.1-flash-image', 'text_to_image,image_to_image',
             'image', true, 'OpenAI-compatible SDK 接入的 Google 3.1 image 模型', true, true, true, '标准', null, 1, 1, 20, false)
        ON CONFLICT (code) DO UPDATE SET
            provider_id = EXCLUDED.provider_id,
            name = EXCLUDED.name,
            vendor_model = EXCLUDED.vendor_model,
            work_type = EXCLUDED.work_type,
            capability_type = EXCLUDED.capability_type,
            supports_image_edit = EXCLUDED.supports_image_edit,
            description = EXCLUDED.description,
            is_recommended = EXCLUDED.is_recommended,
            is_stable = EXCLUDED.is_stable,
            is_new = EXCLUDED.is_new,
            max_input_images = EXCLUDED.max_input_images,
            max_output_images = EXCLUDED.max_output_images
        """
    )
    op.execute(
        """
        INSERT INTO image_model_resolutions (model_id, resolution_id)
        SELECT model.id, spec.id
        FROM image_models model
        JOIN image_resolution_specs spec ON spec.code IN ('1k', '2k', '4k')
        WHERE model.code = 'google-3-1-image'
        ON CONFLICT (model_id, resolution_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO image_model_aspect_ratios (model_id, aspect_ratio_id)
        SELECT model.id, spec.id
        FROM image_models model
        JOIN image_aspect_ratio_specs spec ON spec.code IN ('1:1', '4:3', '3:4', '16:9', '9:16')
        WHERE model.code = 'google-3-1-image'
        ON CONFLICT (model_id, aspect_ratio_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM image_models WHERE code = 'google-3-1-image'")
    op.execute("DELETE FROM image_model_providers WHERE code = 'google-3-1-image-sdk'")
    op.drop_column("image_model_providers", "access_mode")
