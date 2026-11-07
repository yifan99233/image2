from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Column, DateTime, MetaData, String, Table, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_admin, get_db, require_admin_roles
from app.api.endpoints.admin_data import add_audit, scoped_user_condition, users_table
from app.core.exceptions import AppException
from app.models.admin_user import AdminRole, AdminUser
from app.models.benefit_package import BenefitGrant, BenefitPackage, BenefitPackageItem
from app.schemas.benefit_package import BenefitPackageCreate, BenefitPackageOut, BenefitPackageUpdate
from app.schemas.response import ApiResponse
from app.services.benefit_grants import materialize_paid_order_grants
from app.services.site_scope import current_site_id

router = APIRouter(prefix="/benefit-packages")

_team_metadata = MetaData()
user_teams_table = Table(
    "user_teams",
    _team_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("owner_user_id", BigInteger),
)
user_team_members_table = Table(
    "user_team_members",
    _team_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("team_id", BigInteger),
    Column("user_id", BigInteger),
)


class ManualBenefitGrantInput(BaseModel):
    user_id: int = Field(gt=0)
    team_id: int | None = Field(default=None, gt=0)
    starts_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)


def _manual_order_no() -> str:
    return f"BPA{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:10].upper()}"


async def scoped_site_id(db: AsyncSession, request: Request, admin: AdminUser) -> int:
    if admin.system_super_admin:
        return await current_site_id(db, request)
    return int(admin.site_id or 1)


def package_out(package: BenefitPackage) -> BenefitPackageOut:
    return BenefitPackageOut.model_validate(package)


async def package_by_id(db: AsyncSession, site_id: int, package_id: int) -> BenefitPackage | None:
    return await db.scalar(
        select(BenefitPackage)
        .options(selectinload(BenefitPackage.items))
        .where(BenefitPackage.id == package_id, BenefitPackage.site_id == site_id)
    )


def apply_package_fields(package: BenefitPackage, payload: BenefitPackageCreate | BenefitPackageUpdate) -> None:
    values = payload.model_dump(exclude={"items"})
    for key, value in values.items():
        setattr(package, key, value.strip() if isinstance(value, str) else value)


def replace_package_items(package: BenefitPackage, payload: BenefitPackageCreate | BenefitPackageUpdate) -> None:
    package.items.clear()
    package.items.extend(
        BenefitPackageItem(
            resource_type=item.resource_type,
            value_type="numeric",
            amount=item.amount,
            grant_mode=item.grant_mode,
            grant_count=item.grant_count,
            scope=item.scope,
            aggregation_mode=item.aggregation_mode,
            expiry_policy=item.expiry_policy,
            sort_order=item.sort_order,
        )
        for item in payload.items
    )


@router.get("", response_model=ApiResponse[dict])
async def list_benefit_packages(
    request: Request,
    keyword: str = "",
    status: str = Query("all", pattern="^(all|active|inactive)$"),
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[dict]:
    site_id = await scoped_site_id(db, request, current_admin)
    condition = BenefitPackage.site_id == site_id
    if status == "active":
        condition = condition & BenefitPackage.is_active.is_(True)
    elif status == "inactive":
        condition = condition & BenefitPackage.is_active.is_(False)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        condition = condition & or_(BenefitPackage.name.ilike(like), BenefitPackage.code.ilike(like))
    total = await db.scalar(select(func.count()).select_from(BenefitPackage).where(condition))
    result = await db.execute(
        select(BenefitPackage)
        .options(selectinload(BenefitPackage.items))
        .where(condition)
        .order_by(BenefitPackage.sort_order.asc(), BenefitPackage.id.desc())
        .limit(page_size)
        .offset((page_no - 1) * page_size)
    )
    return ApiResponse.ok({
        "items": [package_out(package) for package in result.scalars().unique()],
        "total": int(total or 0),
        "page": page_no,
        "page_size": page_size,
    })


@router.post("", response_model=ApiResponse[BenefitPackageOut])
async def create_benefit_package(
    request: Request,
    payload: BenefitPackageCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[BenefitPackageOut]:
    site_id = await scoped_site_id(db, request, current_admin)
    package = BenefitPackage(site_id=site_id)
    apply_package_fields(package, payload)
    replace_package_items(package, payload)
    db.add(package)
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        if "uq_benefit_packages_site_code" in str(error).lower():
            raise AppException(code=40941, message="套餐编码已存在", status_code=409) from error
        raise
    add_audit(db, current_admin, "create_benefit_package", "benefit_packages", package.id, f"code={package.code}")
    await db.commit()
    package = await package_by_id(db, site_id, package.id)
    return ApiResponse.ok(package_out(package), "权益套餐已创建")


@router.post("/{package_id}/grant", response_model=ApiResponse[dict])
async def grant_benefit_package_manually(
    package_id: int,
    request: Request,
    payload: ManualBenefitGrantInput,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[dict]:
    """Open a configured package directly from the admin console.

    Manual opening creates the same paid order and immutable grant snapshots
    as a successful payment callback. This keeps validity, scheduled grants,
    stacking and versioning identical for sales and operator-issued benefits.
    """
    site_id = await scoped_site_id(db, request, current_admin)
    package = await package_by_id(db, site_id, package_id)
    if package is None:
        raise AppException(code=40441, message="权益套餐不存在", status_code=404)
    user = (
        await db.execute(
            select(users_table.c.id, users_table.c.site_id)
            .where(
                users_table.c.id == payload.user_id,
                users_table.c.deleted_at.is_(None),
                scoped_user_condition(current_admin),
            )
            .with_for_update()
        )
    ).first()
    if user is None or int(user.site_id or 1) != site_id:
        raise AppException(code=40404, message="用户不存在", status_code=404)

    has_team_items = any(item.scope == "team" for item in package.items)
    has_user_items = any(item.scope == "user" for item in package.items)
    team_id = payload.team_id
    if has_team_items:
        if team_id is None:
            team_id = await db.scalar(
                select(user_teams_table.c.id)
                .where(user_teams_table.c.site_id == site_id, user_teams_table.c.owner_user_id == payload.user_id)
                .order_by(user_teams_table.c.id.asc())
                .limit(1)
            )
        if team_id is None:
            raise AppException(code=40944, message="该用户没有可开通权益的团队", status_code=409)
        member_exists = await db.scalar(
            select(user_team_members_table.c.id).where(
                user_team_members_table.c.site_id == site_id,
                user_team_members_table.c.team_id == team_id,
                user_team_members_table.c.user_id == payload.user_id,
            )
        )
        if member_exists is None:
            raise AppException(code=40383, message="用户不是目标团队成员", status_code=403)
    elif team_id is not None:
        raise AppException(code=40090, message="个人权益套餐不能指定团队")
    if has_user_items and team_id is not None and not has_team_items:
        team_id = None

    if payload.starts_at is not None and payload.starts_at.tzinfo is None:
        raise AppException(code=40089, message="开通时间必须包含时区")
    now = datetime.now(UTC)
    starts_at = payload.starts_at.astimezone(UTC) if payload.starts_at is not None else now
    if starts_at < now:
        starts_at = now
    active_orders = (
        await db.execute(
            select(BenefitOrder)
            .where(
                BenefitOrder.package_id == package.id,
                BenefitOrder.payer_user_id == payload.user_id,
                BenefitOrder.status == "paid",
                or_(BenefitOrder.expires_at.is_(None), BenefitOrder.expires_at > now),
                BenefitOrder.team_id.is_(None) if team_id is None else BenefitOrder.team_id == team_id,
            )
            .order_by(BenefitOrder.expires_at.desc().nullslast(), BenefitOrder.id.desc())
        )
    ).scalars().all()
    if package.stacking_policy == "reject" and active_orders:
        raise AppException(code=40983, message="当前套餐仍在有效期内，不能重复开通", status_code=409)
    if package.stacking_policy == "extend":
        latest_expiry = next((order.expires_at for order in active_orders if order.expires_at and order.expires_at > starts_at), None)
        if latest_expiry is not None:
            starts_at = latest_expiry

    source_reference = f"admin:{current_admin.id}:{uuid4().hex}"
    order = BenefitOrder(
        site_id=site_id,
        order_no=_manual_order_no(),
        package_id=package.id,
        package_version=package.version,
        payer_user_id=payload.user_id,
        team_id=int(team_id) if team_id is not None else None,
        amount_cents=0,
        currency=package.currency,
        status="paid",
        payment_provider="admin",
        payment_type="manual",
        payment_trade_no=source_reference,
        paid_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    await db.flush()
    grant_count = await materialize_paid_order_grants(db, order=order, package=package, starts_at=starts_at)
    add_audit(
        db,
        current_admin,
        "grant_benefit_package_manually",
        "benefit_orders",
        order.id,
        f"package_id={package.id}; user_id={payload.user_id}; team_id={team_id}; starts_at={starts_at.isoformat()}; reason={payload.reason.strip()}",
    )
    await db.commit()
    return ApiResponse.ok(
        {
            "order_id": order.id,
            "order_no": order.order_no,
            "package_id": package.id,
            "user_id": payload.user_id,
            "team_id": team_id,
            "grant_count": grant_count,
            "starts_at": order.starts_at,
            "expires_at": order.expires_at,
            "status": order.status,
        },
        "权益套餐已由后台开通",
    )


@router.put("/{package_id}", response_model=ApiResponse[BenefitPackageOut])
async def update_benefit_package(
    package_id: int,
    request: Request,
    payload: BenefitPackageUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[BenefitPackageOut]:
    site_id = await scoped_site_id(db, request, current_admin)
    package = await package_by_id(db, site_id, package_id)
    if package is None:
        raise AppException(code=40441, message="权益套餐不存在", status_code=404)
    grant_count = await db.scalar(select(func.count()).select_from(BenefitGrant).where(BenefitGrant.package_id == package.id))
    if grant_count:
        raise AppException(code=40942, message="套餐已经产生权益发放记录，不能覆盖编辑；请复制为新版本", status_code=409)
    apply_package_fields(package, payload)
    package.version += 1
    replace_package_items(package, payload)
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        if "uq_benefit_packages_site_code" in str(error).lower():
            raise AppException(code=40941, message="套餐编码已存在", status_code=409) from error
        raise
    add_audit(db, current_admin, "update_benefit_package", "benefit_packages", package.id, f"version={package.version}")
    await db.commit()
    package = await package_by_id(db, site_id, package.id)
    return ApiResponse.ok(package_out(package), "权益套餐已更新")


@router.patch("/{package_id}/status", response_model=ApiResponse[BenefitPackageOut])
async def toggle_benefit_package(
    package_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[BenefitPackageOut]:
    site_id = await scoped_site_id(db, request, current_admin)
    package = await package_by_id(db, site_id, package_id)
    if package is None:
        raise AppException(code=40441, message="权益套餐不存在", status_code=404)
    package.is_active = not package.is_active
    add_audit(db, current_admin, "toggle_benefit_package", "benefit_packages", package.id, f"is_active={package.is_active}")
    await db.commit()
    package = await package_by_id(db, site_id, package.id)
    return ApiResponse.ok(package_out(package), "权益套餐状态已更新")
