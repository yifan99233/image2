"""site scoped module configs

Revision ID: 20260706_0240
Revises: 20260706_0230
Create Date: 2026-07-06 02:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260706_0240"
down_revision: str | None = "20260706_0230"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in (
        "image_resolution_specs",
        "image_aspect_ratio_specs",
        "payment_configs",
        "recharge_plans",
        "signin_reward_configs",
        "invite_reward_configs",
        "openagent_releases",
    ):
        op.execute(f"ALTER TABLE IF EXISTS {table_name} ADD COLUMN IF NOT EXISTS site_id BIGINT NOT NULL DEFAULT 1")

    op.execute("ALTER TABLE IF EXISTS image_resolution_specs DROP CONSTRAINT IF EXISTS uq_image_resolution_specs_code")
    op.execute("ALTER TABLE IF EXISTS image_aspect_ratio_specs DROP CONSTRAINT IF EXISTS uq_image_aspect_ratio_specs_code")
    op.execute("ALTER TABLE IF EXISTS payment_configs DROP CONSTRAINT IF EXISTS payment_configs_provider_key")
    op.execute("ALTER TABLE IF EXISTS openagent_releases DROP CONSTRAINT IF EXISTS uq_openagent_releases_target")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_image_resolution_specs_site_code ON image_resolution_specs (site_id, code)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_image_aspect_ratio_specs_site_code ON image_aspect_ratio_specs (site_id, code)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_configs_site_provider ON payment_configs (site_id, provider)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_recharge_plans_site_name ON recharge_plans (site_id, name)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_signin_reward_configs_site ON signin_reward_configs (site_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_invite_reward_configs_site ON invite_reward_configs (site_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_openagent_releases_site_target ON openagent_releases (site_id, channel, version, platform, arch)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_resolution_specs_site_active_sort ON image_resolution_specs (site_id, is_active, sort_order)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_aspect_ratio_specs_site_active_sort ON image_aspect_ratio_specs (site_id, is_active, sort_order)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_recharge_plans_site_active_sort ON recharge_plans (site_id, is_active, sort_order)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_openagent_releases_site_lookup ON openagent_releases (site_id, channel, platform, arch, is_active)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_recharge_plans_site_active_sort")
    op.execute("DROP INDEX IF EXISTS ix_openagent_releases_site_lookup")
    op.execute("DROP INDEX IF EXISTS uq_openagent_releases_site_target")
    op.execute("DROP INDEX IF EXISTS ix_image_aspect_ratio_specs_site_active_sort")
    op.execute("DROP INDEX IF EXISTS ix_image_resolution_specs_site_active_sort")
    op.execute("DROP INDEX IF EXISTS uq_invite_reward_configs_site")
    op.execute("DROP INDEX IF EXISTS uq_signin_reward_configs_site")
    op.execute("DROP INDEX IF EXISTS uq_recharge_plans_site_name")
    op.execute("DROP INDEX IF EXISTS uq_payment_configs_site_provider")
    op.execute("DROP INDEX IF EXISTS uq_image_aspect_ratio_specs_site_code")
    op.execute("DROP INDEX IF EXISTS uq_image_resolution_specs_site_code")
    for table_name in (
        "invite_reward_configs",
        "openagent_releases",
        "signin_reward_configs",
        "recharge_plans",
        "payment_configs",
        "image_aspect_ratio_specs",
        "image_resolution_specs",
    ):
        op.execute(f"ALTER TABLE IF EXISTS {table_name} DROP COLUMN IF EXISTS site_id")
