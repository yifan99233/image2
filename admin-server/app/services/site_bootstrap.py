from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Table, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image_model import ImageModel, ImageModelProvider
from app.models.image_spec import (
    ImageAspectRatioSpec,
    ImageModelAspectRatio,
    ImageModelDuration,
    ImageModelResolution,
    ImageResolutionSpec,
    VideoDurationSpec,
)
from app.models.model_price import ModelPrice
from app.models.openagent_release import OpenAgentRelease
from app.models.recharge_plan import RechargePlan


@dataclass(frozen=True)
class SiteBootstrapResult:
    providers: int = 0
    models: int = 0
    model_prices: int = 0
    image_resolutions: int = 0
    aspect_ratios: int = 0
    video_durations: int = 0
    recharge_plans: int = 0
    openagent_releases: int = 0
    module_configs: int = 0

    @property
    def total(self) -> int:
        return sum(
            (
                self.providers,
                self.models,
                self.model_prices,
                self.image_resolutions,
                self.aspect_ratios,
                self.video_durations,
                self.recharge_plans,
                self.openagent_releases,
                self.module_configs,
            )
        )


_SYSTEM_COLUMNS = {"id", "site_id", "created_at", "updated_at"}


def _copyable_values(
    table: Table,
    row: Mapping[str, Any],
    *,
    target_site_id: int | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    column_names = {column.name for column in table.columns}
    values = {
        key: value
        for key, value in row.items()
        if key in column_names and key not in _SYSTEM_COLUMNS
    }
    if target_site_id is not None and "site_id" in column_names:
        values["site_id"] = target_site_id
    if overrides:
        values.update({key: value for key, value in overrides.items() if key in column_names})
    return values


async def _clone_rows_with_id_map(
    db: AsyncSession,
    table: Table,
    source_condition,
    *,
    target_site_id: int | None = None,
    overrides: Mapping[str, Any] | None = None,
    foreign_key_maps: Mapping[str, Mapping[int, int]] | None = None,
) -> dict[int, int]:
    rows = (await db.execute(select(table).where(source_condition).order_by(table.c.id))).mappings().all()
    id_map: dict[int, int] = {}
    for row in rows:
        values = _copyable_values(table, row, target_site_id=target_site_id, overrides=overrides)
        for column_name, value_map in (foreign_key_maps or {}).items():
            source_value = values.get(column_name)
            if source_value is not None:
                values[column_name] = value_map[int(source_value)]
        new_id = await db.scalar(insert(table).values(**values).returning(table.c.id))
        id_map[int(row["id"])] = int(new_id)
    return id_map


async def _clone_associations(
    db: AsyncSession,
    table: Table,
    *,
    source_model_ids: Sequence[int],
    foreign_key_maps: Mapping[str, Mapping[int, int]],
) -> int:
    if not source_model_ids:
        return 0
    rows = (
        await db.execute(
            select(table)
            .where(table.c.model_id.in_(source_model_ids))
            .order_by(table.c.id)
        )
    ).mappings().all()
    for row in rows:
        values = _copyable_values(table, row)
        for column_name, value_map in foreign_key_maps.items():
            values[column_name] = value_map[int(values[column_name])]
        await db.execute(insert(table).values(**values))
    return len(rows)


async def _clone_simple_site_table(
    db: AsyncSession,
    table: Table,
    *,
    source_site_id: int,
    target_site_id: int,
    overrides: Mapping[str, Any] | None = None,
) -> int:
    rows = (
        await db.execute(
            select(table)
            .where(table.c.site_id == source_site_id)
            .order_by(table.c.id)
        )
    ).mappings().all()
    next_id = int((await db.scalar(select(func.coalesce(func.max(table.c.id), 0) + 1))) or 1)
    for row in rows:
        values = _copyable_values(table, row, target_site_id=target_site_id, overrides=overrides)
        values["id"] = next_id
        await db.execute(insert(table).values(**values))
        next_id += 1
    return len(rows)


async def clone_site_bootstrap(
    db: AsyncSession,
    *,
    source_site_id: int,
    target_site_id: int,
    updated_by: int,
    module_config_tables: Sequence[Table],
    payment_config_table: Table,
    frontend_url: str,
) -> SiteBootstrapResult:
    """Clone reusable tenant configuration while leaving users and business data behind."""
    provider_ids = await _clone_rows_with_id_map(
        db,
        ImageModelProvider.__table__,
        ImageModelProvider.site_id == source_site_id,
        target_site_id=target_site_id,
    )
    resolution_ids = await _clone_rows_with_id_map(
        db,
        ImageResolutionSpec.__table__,
        ImageResolutionSpec.site_id == source_site_id,
        target_site_id=target_site_id,
    )
    aspect_ratio_ids = await _clone_rows_with_id_map(
        db,
        ImageAspectRatioSpec.__table__,
        ImageAspectRatioSpec.site_id == source_site_id,
        target_site_id=target_site_id,
    )
    duration_ids = await _clone_rows_with_id_map(
        db,
        VideoDurationSpec.__table__,
        VideoDurationSpec.site_id == source_site_id,
        target_site_id=target_site_id,
    )
    model_ids = await _clone_rows_with_id_map(
        db,
        ImageModel.__table__,
        ImageModel.site_id == source_site_id,
        target_site_id=target_site_id,
        foreign_key_maps={"provider_id": provider_ids},
    )
    source_model_ids = list(model_ids)
    await _clone_associations(
        db,
        ImageModelResolution.__table__,
        source_model_ids=source_model_ids,
        foreign_key_maps={"model_id": model_ids, "resolution_id": resolution_ids},
    )
    await _clone_associations(
        db,
        ImageModelAspectRatio.__table__,
        source_model_ids=source_model_ids,
        foreign_key_maps={"model_id": model_ids, "aspect_ratio_id": aspect_ratio_ids},
    )
    await _clone_associations(
        db,
        ImageModelDuration.__table__,
        source_model_ids=source_model_ids,
        foreign_key_maps={"model_id": model_ids, "duration_id": duration_ids},
    )
    model_price_ids = await _clone_rows_with_id_map(
        db,
        ModelPrice.__table__,
        ModelPrice.site_id == source_site_id,
        target_site_id=target_site_id,
        foreign_key_maps={"model_id": model_ids},
    )
    recharge_plan_ids = await _clone_rows_with_id_map(
        db,
        RechargePlan.__table__,
        RechargePlan.site_id == source_site_id,
        target_site_id=target_site_id,
    )
    openagent_release_ids = await _clone_rows_with_id_map(
        db,
        OpenAgentRelease.__table__,
        OpenAgentRelease.site_id == source_site_id,
        target_site_id=target_site_id,
    )

    module_config_count = 0
    for table in module_config_tables:
        module_config_count += await _clone_simple_site_table(
            db,
            table,
            source_site_id=source_site_id,
            target_site_id=target_site_id,
            overrides={"updated_by": updated_by},
        )

    clean_frontend_url = frontend_url.rstrip("/")
    payment_overrides: dict[str, Any] = {"updated_by": updated_by}
    if clean_frontend_url:
        payment_overrides.update(
            {
                "notify_url": f"{clean_frontend_url}/api/recharge/zpay/notify",
                "return_url": f"{clean_frontend_url}/billing/recharge",
            }
        )
    module_config_count += await _clone_simple_site_table(
        db,
        payment_config_table,
        source_site_id=source_site_id,
        target_site_id=target_site_id,
        overrides=payment_overrides,
    )

    return SiteBootstrapResult(
        providers=len(provider_ids),
        models=len(model_ids),
        model_prices=len(model_price_ids),
        image_resolutions=len(resolution_ids),
        aspect_ratios=len(aspect_ratio_ids),
        video_durations=len(duration_ids),
        recharge_plans=len(recharge_plan_ids),
        openagent_releases=len(openagent_release_ids),
        module_configs=module_config_count,
    )
