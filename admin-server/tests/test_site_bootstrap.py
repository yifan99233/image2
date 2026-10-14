from sqlalchemy import BigInteger, Column, DateTime, MetaData, String, Table

from app.services.site_bootstrap import SiteBootstrapResult, _copyable_values


def test_copyable_values_replaces_tenant_and_drops_identity_columns():
    table = Table(
        "example_configs",
        MetaData(),
        Column("id", BigInteger),
        Column("site_id", BigInteger),
        Column("name", String),
        Column("updated_by", BigInteger),
        Column("created_at", DateTime(timezone=True)),
        Column("updated_at", DateTime(timezone=True)),
    )

    values = _copyable_values(
        table,
        {
            "id": 91,
            "site_id": 2,
            "name": "art-template",
            "updated_by": 7,
            "created_at": "old-created-at",
            "updated_at": "old-updated-at",
        },
        target_site_id=12,
        overrides={"updated_by": 31},
    )

    assert values == {"site_id": 12, "name": "art-template", "updated_by": 31}


def test_bootstrap_result_total_counts_all_configuration_groups():
    result = SiteBootstrapResult(
        providers=2,
        models=3,
        model_prices=4,
        image_resolutions=5,
        aspect_ratios=6,
        video_durations=7,
        recharge_plans=8,
        openagent_releases=9,
        module_configs=10,
    )

    assert result.total == 54
