from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.benefit_package import BenefitGrant, BenefitOrder, BenefitPackage, BenefitPackageItem


@dataclass(frozen=True)
class GrantWindow:
    grant_index: int
    grant_at: datetime
    starts_at: datetime
    expires_at: datetime | None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AppException(code=40089, message="开通时间必须包含时区")
    return value.astimezone(UTC)


def _package_timezone(package: BenefitPackage) -> ZoneInfo:
    try:
        return ZoneInfo(package.timezone or "UTC")
    except ZoneInfoNotFoundError as error:
        raise AppException(code=40088, message="套餐时区无效") from error


def _add_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))


def package_expires_at(package: BenefitPackage, starts_at: datetime) -> datetime | None:
    start = _ensure_utc(starts_at)
    local_start = start.astimezone(_package_timezone(package))
    if package.validity_mode == "permanent":
        return None
    if package.validity_mode == "fixed_days":
        if not package.validity_value or package.validity_value <= 0:
            raise AppException(code=40081, message="固定天数套餐必须配置有效期")
        return (local_start + timedelta(days=package.validity_value)).astimezone(UTC)
    interval = package.billing_interval
    if interval == "month":
        return _add_calendar_months(local_start, 1).astimezone(UTC)
    if interval == "quarter":
        return _add_calendar_months(local_start, 3).astimezone(UTC)
    if interval == "year":
        return _add_calendar_months(local_start, 12).astimezone(UTC)
    raise AppException(code=40083, message="按订阅周期计费的套餐必须配置月、季或年周期")


def grant_schedule(
    package: BenefitPackage,
    item: BenefitPackageItem,
    *,
    starts_at: datetime,
    package_expires: datetime | None,
) -> list[GrantWindow]:
    start = _ensure_utc(starts_at)
    if item.grant_mode == "one_time":
        count, step_days = 1, 0
    else:
        if not item.grant_count or item.grant_count <= 0:
            raise AppException(code=40086, message="按周期发放的权益必须配置发放次数")
        count, step_days = item.grant_count, (1 if item.grant_mode == "daily" else 7)
    local_start = start.astimezone(_package_timezone(package))
    windows: list[GrantWindow] = []
    for index in range(count):
        grant_at = (local_start + timedelta(days=step_days * index)).astimezone(UTC)
        if package_expires is not None and grant_at >= package_expires:
            break
        if item.expiry_policy == "permanent":
            expires_at = None
        elif item.expiry_policy == "package_end":
            expires_at = package_expires
        else:
            next_grant_at = (
                (local_start + timedelta(days=step_days * (index + 1))).astimezone(UTC)
                if step_days
                else package_expires
            )
            expires_at = min(value for value in (next_grant_at, package_expires) if value is not None)
        windows.append(GrantWindow(index + 1, grant_at, grant_at, expires_at))
    if not windows:
        raise AppException(code=40087, message="权益发放次数超出套餐有效期")
    return windows


async def materialize_paid_order_grants(
    db: AsyncSession,
    *,
    order: BenefitOrder,
    package: BenefitPackage,
    starts_at: datetime,
) -> int:
    starts = _ensure_utc(starts_at)
    package_end = package_expires_at(package, starts)
    created = 0
    for item in package.items:
        grant_team_id = order.team_id if item.scope == "team" else None
        for window in grant_schedule(package, item, starts_at=starts, package_expires=package_end):
            key = f"benefit:{order.order_no}:{item.id}:{window.grant_index}"
            if await db.scalar(select(BenefitGrant.id).where(BenefitGrant.idempotency_key == key)) is not None:
                continue
            db.add(
                BenefitGrant(
                    site_id=order.site_id,
                    order_id=order.id,
                    package_id=package.id,
                    package_item_id=item.id,
                    package_version=package.version,
                    owner_user_id=order.payer_user_id,
                    team_id=grant_team_id,
                    resource_type=item.resource_type,
                    amount=Decimal(item.amount),
                    remaining_amount=Decimal(item.amount),
                    grant_mode=item.grant_mode,
                    grant_index=window.grant_index,
                    grant_at=window.grant_at,
                    starts_at=window.starts_at,
                    expires_at=window.expires_at,
                    status="active" if window.grant_at <= datetime.now(UTC) else "scheduled",
                    idempotency_key=key,
                )
            )
            created += 1
    order.starts_at = starts
    order.expires_at = package_end
    await db.flush()
    return created
