from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.models.benefit_package import BenefitCreditAllocation, BenefitGrant, BenefitOrder, BenefitPackage, BenefitPackageItem
from app.models.credit import CreditLedger, UserCreditAccount

logger = logging.getLogger(__name__)


RESOURCE_TYPES = frozenset(
    {
        "credits",
        "team_seats",
        "image_concurrency",
        "video_concurrency",
        "task_queue_limit",
        "api_quota",
        "storage_quota",
    }
)
GRANT_MODES = frozenset({"one_time", "daily", "weekly"})


@dataclass(frozen=True)
class GrantWindow:
    grant_index: int
    grant_at: datetime
    starts_at: datetime
    expires_at: datetime | None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _add_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    # The subscription period is anchored to the last valid day of the target
    # month instead of silently overflowing into the following month.
    from calendar import monthrange

    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _package_timezone(package: BenefitPackage) -> ZoneInfo:
    try:
        return ZoneInfo(package.timezone or "UTC")
    except ZoneInfoNotFoundError as error:
        raise BusinessError("套餐时区无效", code=40088) from error


def package_expires_at(package: BenefitPackage, starts_at: datetime) -> datetime | None:
    start = _ensure_utc(starts_at)
    local_start = start.astimezone(_package_timezone(package))
    if package.validity_mode == "permanent":
        return None
    if package.validity_mode == "fixed_days":
        if not package.validity_value or package.validity_value <= 0:
            raise BusinessError("固定天数套餐必须配置有效期", code=40081)
        return (local_start + timedelta(days=package.validity_value)).astimezone(UTC)
    if package.validity_mode != "billing_period":
        raise BusinessError("套餐有效期类型无效", code=40082)
    interval = package.billing_interval
    if interval == "month":
        return _add_calendar_months(local_start, 1).astimezone(UTC)
    if interval == "quarter":
        return _add_calendar_months(local_start, 3).astimezone(UTC)
    if interval == "year":
        return _add_calendar_months(local_start, 12).astimezone(UTC)
    raise BusinessError("按订阅周期计费的套餐必须配置月、季或年周期", code=40083)


def grant_schedule(
    package: BenefitPackage,
    item: BenefitPackageItem,
    *,
    starts_at: datetime,
    package_expires: datetime | None,
) -> list[GrantWindow]:
    start = _ensure_utc(starts_at)
    if item.resource_type not in RESOURCE_TYPES:
        raise BusinessError("权益类型不受支持", code=40084)
    if item.grant_mode not in GRANT_MODES:
        raise BusinessError("权益发放方式不受支持", code=40085)
    if item.grant_mode == "one_time":
        count = 1
        step_days = 0
    else:
        if not item.grant_count or item.grant_count <= 0:
            raise BusinessError("按周期发放的权益必须配置发放次数", code=40086)
        count = item.grant_count
        step_days = 1 if item.grant_mode == "daily" else 7

    windows: list[GrantWindow] = []
    local_start = start.astimezone(_package_timezone(package))
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
        raise BusinessError("权益发放次数超出套餐有效期", code=40087)
    return windows


async def materialize_paid_order_grants(
    db: AsyncSession,
    *,
    order: BenefitOrder,
    package: BenefitPackage,
    starts_at: datetime,
) -> int:
    """Create immutable grant rows for a paid order.

    The unique idempotency key makes webhook retries and scheduler retries safe.
    This function only materializes entitlements; a separate worker applies due
    grants to wallets and team limits.
    """
    if order.status != "paid":
        raise BusinessError("只有已支付订单才能发放权益", code=40981)
    starts = _ensure_utc(starts_at)
    package_end = package_expires_at(package, starts)
    created = 0
    for item in package.items:
        grant_team_id = order.team_id if item.scope == "team" else None
        for window in grant_schedule(package, item, starts_at=starts, package_expires=package_end):
            key = f"benefit:{order.order_no}:{item.id}:{window.grant_index}"
            existing = await db.scalar(select(BenefitGrant.id).where(BenefitGrant.idempotency_key == key))
            if existing is not None:
                continue
            status = "active" if window.grant_at <= datetime.now(UTC) else "scheduled"
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
                    status=status,
                    idempotency_key=key,
                )
            )
            created += 1
    order.starts_at = starts
    order.expires_at = package_end
    await db.flush()
    return created


async def apply_due_benefit_grants(db: AsyncSession, *, order: BenefitOrder, now: datetime | None = None) -> int:
    """Activate due grants and credit numeric wallet benefits exactly once.

    Non-credit resources remain as immutable entitlement rows and are resolved
    by their resource-specific quota readers. Credit grants are mirrored into
    the existing local account so old clients continue to see the same balance.
    """
    current_time = _ensure_utc(now or datetime.now(UTC))
    await db.execute(
        update(BenefitGrant)
        .where(
            BenefitGrant.order_id == order.id,
            BenefitGrant.status == "scheduled",
            BenefitGrant.grant_at <= current_time,
        )
        .values(status="active", updated_at=current_time)
    )
    rows = (
        await db.execute(
            select(BenefitGrant)
            .where(
                BenefitGrant.order_id == order.id,
                BenefitGrant.status == "active",
                BenefitGrant.grant_at <= current_time,
                (BenefitGrant.expires_at.is_(None)) | (BenefitGrant.expires_at > current_time),
            )
            .with_for_update()
        )
    ).scalars().all()
    if not rows:
        return 0
    from app.services.sub2_image_billing import credit_recharge_balance

    account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == order.payer_user_id).with_for_update())
    if account is None:
        account = UserCreditAccount(user_id=order.payer_user_id)
        db.add(account)
        await db.flush()
    applied = 0
    for grant in rows:
        if grant.resource_type != "credits":
            continue
        key = f"benefit-grant-credit:{grant.id}"
        already_applied = await db.scalar(select(CreditLedger.id).where(CreditLedger.idempotency_key == key))
        if already_applied is not None:
            continue
        amount = Decimal(grant.amount)
        await credit_recharge_balance(db, user_id=order.payer_user_id, order_no=key, credit_amount=amount)
        before = account.balance
        account.balance += amount
        account.gift_balance += amount
        account.total_gifted += amount
        account.version += 1
        db.add(
            CreditLedger(
                user_id=order.payer_user_id,
                account_id=account.id,
                direction="credit",
                gift_amount=amount,
                amount=amount,
                balance_before=before,
                balance_after=account.balance,
                biz_type="benefit_grant",
                biz_id=str(grant.id),
                idempotency_key=key,
                description=f"权益套餐发放 {amount} 积分",
                operator_type="system",
            )
        )
        applied += 1
    await db.flush()
    return applied


async def expire_benefit_grants(db: AsyncSession, *, now: datetime | None = None, limit: int = 500) -> int:
    """Expire grants and claw back unconsumed credit lots idempotently."""
    current_time = _ensure_utc(now or datetime.now(UTC))
    rows = (
        await db.execute(
            select(BenefitGrant)
            .where(
                BenefitGrant.status.in_(["scheduled", "active"]),
                BenefitGrant.expires_at.is_not(None),
                BenefitGrant.expires_at <= current_time,
            )
            .order_by(BenefitGrant.expires_at.asc(), BenefitGrant.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    from app.api.routes.catalog import add_credit_ledger, get_or_create_credit_account_for_update
    from app.services.sub2_image_billing import debit_image_task_balance

    for grant in rows:
        if grant.resource_type == "credits" and Decimal(grant.remaining_amount or 0) > 0:
            amount = Decimal(grant.remaining_amount)
            try:
                await debit_image_task_balance(
                    db,
                    user_id=grant.owner_user_id,
                    task_no=f"benefit-expiry:{grant.id}",
                    credit_amount=amount,
                )
            except BusinessError:
                # Keep the grant active until the external wallet confirms the
                # clawback; the next worker pass will retry it.
                continue
            account = await get_or_create_credit_account_for_update(db, grant.owner_user_id)
            before = account.balance
            account.balance -= amount
            account.gift_balance = max(Decimal("0"), account.gift_balance - amount)
            account.total_gifted = max(Decimal("0"), account.total_gifted - amount)
            account.version += 1
            add_credit_ledger(
                db=db,
                account=account,
                user_id=grant.owner_user_id,
                direction="debit",
                amount=amount,
                balance_before=before,
                balance_after=account.balance,
                biz_type="benefit_expiry",
                biz_id=str(grant.id),
                idempotency_key=f"benefit-expiry-ledger:{grant.id}",
                description=f"权益积分过期 {amount}",
                gift_amount=amount,
                operator_type="system",
            )
            grant.remaining_amount = Decimal("0")
        grant.status = "expired"
    await db.flush()
    return len(rows)


def validate_timezone(timezone_name: str) -> str:
    normalized = timezone_name.strip()
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as error:
        raise BusinessError("套餐时区无效", code=40088) from error
    return normalized


async def active_team_resource_total(
    db: AsyncSession,
    *,
    site_id: int,
    team_id: int,
    resource_type: str,
    now: datetime | None = None,
) -> Decimal:
    """Resolve a numeric team entitlement from active immutable grants.

    Aggregation is evaluated from the immutable package item configuration:
    ``sum`` adds grants, ``max`` takes the largest active grant, and
    ``replace`` uses the newest active grant.  Different modes can coexist in
    one resource; their results are added so each configured item remains
    visible and deterministic.
    """
    current_time = _ensure_utc(now or datetime.now(UTC))
    rows = (
        await db.execute(
            select(BenefitGrant.remaining_amount, BenefitPackageItem.aggregation_mode, BenefitGrant.grant_at, BenefitGrant.id)
            .join(BenefitPackageItem, BenefitPackageItem.id == BenefitGrant.package_item_id)
            .where(
                BenefitGrant.site_id == site_id,
                BenefitGrant.team_id == team_id,
                BenefitGrant.resource_type == resource_type,
                BenefitGrant.status.in_(["active", "scheduled"]),
                BenefitGrant.grant_at <= current_time,
                or_(BenefitGrant.expires_at.is_(None), BenefitGrant.expires_at > current_time),
            )
        )
    ).all()
    return _aggregate_entitlement_rows(rows)


async def active_user_resource_total(
    db: AsyncSession,
    *,
    site_id: int,
    user_id: int,
    resource_type: str,
    now: datetime | None = None,
) -> Decimal:
    """Resolve a numeric personal entitlement from active immutable grants."""
    current_time = _ensure_utc(now or datetime.now(UTC))
    rows = (
        await db.execute(
            select(BenefitGrant.remaining_amount, BenefitPackageItem.aggregation_mode, BenefitGrant.grant_at, BenefitGrant.id)
            .join(BenefitPackageItem, BenefitPackageItem.id == BenefitGrant.package_item_id)
            .where(
                BenefitGrant.site_id == site_id,
                BenefitGrant.owner_user_id == user_id,
                BenefitGrant.team_id.is_(None),
                BenefitGrant.resource_type == resource_type,
                BenefitGrant.status.in_(["active", "scheduled"]),
                BenefitGrant.grant_at <= current_time,
                or_(BenefitGrant.expires_at.is_(None), BenefitGrant.expires_at > current_time),
            )
        )
    ).all()
    return _aggregate_entitlement_rows(rows)


def _aggregate_entitlement_rows(rows) -> Decimal:
    sums = Decimal("0")
    maximum = Decimal("0")
    newest_replace: tuple[datetime, int, Decimal] | None = None
    for amount, aggregation_mode, grant_at, grant_id in rows:
        value = Decimal(amount or 0)
        mode = str(aggregation_mode or "sum")
        if mode == "max":
            maximum = max(maximum, value)
        elif mode == "replace":
            marker = (_ensure_utc(grant_at), int(grant_id), value)
            if newest_replace is None or marker[:2] > newest_replace[:2]:
                newest_replace = marker
        else:
            sums += value
    return sums + maximum + (newest_replace[2] if newest_replace else Decimal("0"))


async def allocate_benefit_credits(
    db: AsyncSession,
    *,
    user_id: int,
    team_id: int | None,
    amount: Decimal,
    task_no: str,
    now: datetime | None = None,
) -> Decimal:
    """Allocate a debit to unexpired subscription credit lots in FIFO order."""
    remaining = Decimal(amount)
    if remaining <= 0:
        return Decimal("0")
    current_time = _ensure_utc(now or datetime.now(UTC))
    existing = await db.scalar(
        select(func.coalesce(func.sum(BenefitCreditAllocation.amount), 0)).where(
            BenefitCreditAllocation.task_no == task_no,
            BenefitCreditAllocation.released_at.is_(None),
        )
    )
    remaining -= Decimal(existing or 0)
    if remaining <= 0:
        return Decimal("0")
    condition = BenefitGrant.team_id == team_id if team_id is not None else (
        (BenefitGrant.owner_user_id == user_id) & BenefitGrant.team_id.is_(None)
    )
    grants = (
        await db.execute(
            select(BenefitGrant)
            .where(
                condition,
                BenefitGrant.owner_user_id == user_id if team_id is None else BenefitGrant.team_id == team_id,
                BenefitGrant.resource_type == "credits",
                BenefitGrant.status == "active",
                BenefitGrant.remaining_amount > 0,
                BenefitGrant.grant_at <= current_time,
                or_(BenefitGrant.expires_at.is_(None), BenefitGrant.expires_at > current_time),
            )
            .order_by(BenefitGrant.expires_at.asc().nullslast(), BenefitGrant.grant_at.asc(), BenefitGrant.id.asc())
            .with_for_update()
        )
    ).scalars().all()
    for grant in grants:
        if remaining <= 0:
            break
        allocated = min(Decimal(grant.remaining_amount), remaining)
        db.add(BenefitCreditAllocation(grant_id=grant.id, user_id=user_id, team_id=team_id, task_no=task_no, amount=allocated))
        grant.remaining_amount -= allocated
        if grant.remaining_amount <= 0:
            grant.remaining_amount = Decimal("0")
            grant.status = "exhausted"
        remaining -= allocated
    await db.flush()
    return remaining


async def release_benefit_credit_allocations(db: AsyncSession, *, task_no: str, now: datetime | None = None) -> Decimal:
    current_time = _ensure_utc(now or datetime.now(UTC))
    allocations = (
        await db.execute(
            select(BenefitCreditAllocation, BenefitGrant)
            .join(BenefitGrant, BenefitGrant.id == BenefitCreditAllocation.grant_id)
            .where(BenefitCreditAllocation.task_no == task_no, BenefitCreditAllocation.released_at.is_(None))
            .with_for_update()
        )
    ).all()
    released = Decimal("0")
    for allocation, grant in allocations:
        allocation.released_at = current_time
        if grant.expires_at is None or grant.expires_at > current_time:
            grant.remaining_amount += allocation.amount
            if grant.status == "exhausted":
                grant.status = "active"
        released += allocation.amount
    await db.flush()
    return released


async def apply_due_benefit_grants_batch(db: AsyncSession, *, now: datetime | None = None, limit: int = 100) -> int:
    current_time = _ensure_utc(now or datetime.now(UTC))
    order_ids = (
        await db.execute(
            select(BenefitOrder.id)
            .join(BenefitGrant, BenefitGrant.order_id == BenefitOrder.id)
            .where(
                BenefitOrder.status == "paid",
                BenefitGrant.status.in_(["scheduled", "active"]),
                BenefitGrant.grant_at <= current_time,
                (BenefitGrant.expires_at.is_(None)) | (BenefitGrant.expires_at > current_time),
            )
            .distinct()
            .order_by(BenefitOrder.id.asc())
            .limit(limit)
        )
    ).scalars().all()
    applied = 0
    for order_id in order_ids:
        order = await db.scalar(select(BenefitOrder).where(BenefitOrder.id == order_id).with_for_update())
        if order is not None:
            applied += await apply_due_benefit_grants(db, order=order, now=current_time)
    return applied


async def benefit_grant_worker_loop(session_factory, interval_seconds: int = 30) -> None:
    while True:
        try:
            async with session_factory() as db:
                await apply_due_benefit_grants_batch(db)
                await expire_benefit_grants(db)
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("benefit grant worker failed")
        await asyncio.sleep(max(5, interval_seconds))
