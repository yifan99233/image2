from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin_roles
from app.api.endpoints.admin_data import add_audit, current_admin_config_site_id, scoped_user_condition, users_table
from app.core.exceptions import AppException
from app.models.admin_user import AdminRole, AdminUser
from app.schemas.response import ApiResponse
from app.services.customer_vip import memberships, tiers

router = APIRouter()
reader = require_admin_roles(AdminRole.super_admin, AdminRole.finance, AdminRole.operator)
writer = require_admin_roles(AdminRole.super_admin, AdminRole.finance)


class TierInput(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    discount_rate: Decimal = Field(ge=Decimal("0.01"), le=1, decimal_places=4)
    is_active: bool = True
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("name", "reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("名称和原因不能为空")
        return value.strip()


class MembershipInput(BaseModel):
    tier_id: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value):
        if value is not None and (value.tzinfo is None or value <= datetime.now(timezone.utc)):
            raise ValueError("有效期必须是含时区的未来时间")
        return value

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("请填写变更原因")
        return value.strip()


@router.get("/vip-tiers", response_model=ApiResponse[list])
async def list_tiers(request: Request, site_id: int | None = None, db: AsyncSession = Depends(get_db),
                     admin: AdminUser = Depends(reader)):
    scope = await current_admin_config_site_id(db, request, admin)
    if site_id is not None:
        if not admin.system_super_admin and site_id != scope:
            raise AppException(code=40301, message="不能访问其他站点", status_code=403)
        scope = site_id
    rows = (await db.execute(select(tiers).where(tiers.c.site_id == scope).order_by(tiers.c.id).limit(100))).mappings().all()
    return ApiResponse.ok([dict(row) for row in rows])


async def save_tier(request, payload, db, admin, tier_id=None):
    site_id = await current_admin_config_site_id(db, request, admin)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"vip-tiers:{site_id}"})
    before = None
    if tier_id is not None:
        before = (await db.execute(select(tiers).where(tiers.c.id == tier_id, tiers.c.site_id == site_id).with_for_update())).mappings().first()
        if before is None:
            raise AppException(code=40401, message="VIP 等级不存在", status_code=404)
    elif (await db.scalar(select(func.count()).select_from(tiers).where(tiers.c.site_id == site_id))) >= 100:
        raise AppException(code=40001, message="每个站点最多配置 100 个 VIP 等级")
    values = {"name": payload.name, "discount_rate": payload.discount_rate, "is_active": payload.is_active,
              "updated_at": datetime.now(timezone.utc)}
    try:
        if tier_id is None:
            tier_id = await db.scalar(insert(tiers).values(**values, site_id=site_id).returning(tiers.c.id))
        else:
            await db.execute(update(tiers).where(tiers.c.id == tier_id, tiers.c.site_id == site_id).values(**values))
        add_audit(db, admin, "save_vip_tier", "customer_vip_tiers", tier_id,
                  f"{payload.reason}；原等级={dict(before) if before else None}；新等级={values}")
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppException(code=40001, message="该站点已有同名 VIP 等级") from exc
    return ApiResponse.ok({"id": tier_id})


@router.post("/vip-tiers", response_model=ApiResponse[dict])
async def create_tier(request: Request, payload: TierInput, db: AsyncSession = Depends(get_db), admin: AdminUser = Depends(writer)):
    return await save_tier(request, payload, db, admin)


@router.put("/vip-tiers/{tier_id}", response_model=ApiResponse[dict])
async def update_tier(tier_id: int, request: Request, payload: TierInput, db: AsyncSession = Depends(get_db), admin: AdminUser = Depends(writer)):
    return await save_tier(request, payload, db, admin, tier_id)


@router.put("/users/{user_id}/vip", response_model=ApiResponse[dict])
async def assign_vip(user_id: int, payload: MembershipInput, db: AsyncSession = Depends(get_db), admin: AdminUser = Depends(writer)):
    user = (await db.execute(select(users_table.c.id, users_table.c.site_id).where(users_table.c.id == user_id,
        users_table.c.deleted_at.is_(None), scoped_user_condition(admin)).with_for_update())).first()
    if user is None:
        raise AppException(code=40401, message="客户不存在", status_code=404)
    before = (await db.execute(select(memberships).where(memberships.c.user_id == user_id))).mappings().first()
    if payload.tier_id is None:
        await db.execute(delete(memberships).where(memberships.c.user_id == user_id))
    else:
        tier = await db.scalar(select(tiers.c.id).where(tiers.c.id == payload.tier_id,
            tiers.c.site_id == user.site_id, tiers.c.is_active.is_(True)).with_for_update())
        if tier is None:
            raise AppException(code=40001, message="VIP 等级不可用或不属于客户所在站点")
        values = {"site_id": user.site_id, "tier_id": tier, "expires_at": payload.expires_at,
                  "updated_at": datetime.now(timezone.utc)}
        await db.execute(pg_insert(memberships).values(user_id=user_id, **values)
                         .on_conflict_do_update(index_elements=[memberships.c.user_id], set_=values))
    add_audit(db, admin, "assign_customer_vip", "users", user_id,
        f"{payload.reason}；原会员={dict(before) if before else None}；新等级={payload.tier_id}；有效期={payload.expires_at}")
    await db.commit()
    return ApiResponse.ok({"user_id": user_id, "tier_id": payload.tier_id, "expires_at": payload.expires_at})
