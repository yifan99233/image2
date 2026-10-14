import hashlib
import secrets
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin_roles
from app.core.exceptions import AppException
from app.models.admin_audit_log import AdminAuditLog
from app.models.admin_user import AdminRole, AdminUser
from app.models.redemption import RedemptionBatch, RedemptionCode
from app.schemas.response import ApiResponse
from app.services.site_scope import current_site_id

router = APIRouter(prefix="/admin/redemption-codes", tags=["redemption-codes"])
admin_access = require_admin_roles(AdminRole.super_admin, AdminRole.finance, AdminRole.operator)


class GenerateCodes(BaseModel):
    request_id: UUID
    amount: int = Field(ge=1, le=1_000_000, strict=True)
    count: int = Field(default=1, ge=1, le=1000, strict=True)
    note: str = Field(default="", max_length=200)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value):
        if value is not None and (value.tzinfo is None or value <= datetime.now(timezone.utc)):
            raise ValueError("有效期必须为未来时间（含时区）")
        return value


async def site_scope(db, request, admin):
    return await current_site_id(db, request) if admin.system_super_admin else int(admin.site_id)


def code_out(row):
    status = row.status
    if status == "unused" and row.expires_at and row.expires_at <= datetime.now(timezone.utc):
        status = "expired"
    return {key: getattr(row, key) for key in (
        "id", "batch_id", "code_hint", "amount", "note", "created_by", "redeemed_by",
        "expires_at", "created_at", "redeemed_at",
    )} | {"status": status}


def audit(db, admin, action, resource_id, reason):
    db.add(AdminAuditLog(admin_id=admin.id, admin_username=admin.username,
                         action=action, resource_type="redemption_code",
                         resource_id=resource_id, reason=reason))


@router.post("")
async def generate_codes(payload: GenerateCodes, request: Request,
                         admin: AdminUser = Depends(admin_access), db: AsyncSession = Depends(get_db)):
    site_id = await site_scope(db, request, admin)
    batch_id = str(payload.request_id)
    db.add(RedemptionBatch(id=batch_id, site_id=site_id, created_by=admin.id))
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        raise AppException(code=40901, message="该批次已生成，请在列表查询；完整兑换码只展示一次", status_code=409) from error
    result = []
    for _ in range(payload.count):
        # 160 bits of entropy. Normalization allows pasted separators and lowercase.
        raw = secrets.token_hex(20).upper()
        code = "-".join(raw[i:i + 8] for i in range(0, len(raw), 8))
        row = RedemptionCode(id=str(uuid4()), site_id=site_id, batch_id=batch_id,
                             code_hash=hashlib.sha256(raw.encode()).hexdigest(), code_hint=raw[-8:],
                             amount=payload.amount, note=payload.note.strip(), created_by=admin.id,
                             expires_at=payload.expires_at, status="unused")
        db.add(row)
        result.append({"code": code, "amount": payload.amount})
    audit(db, admin, "redemption.generate", batch_id,
          f"site={site_id}; count={payload.count}; amount={payload.amount}")
    await db.commit()
    return ApiResponse.ok({"batch_id": batch_id, "codes": result})


@router.get("")
async def list_codes(request: Request, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                     status: Literal["unused", "processing", "redeemed", "disabled", "expired"] | None = None,
                     batch_id: UUID | None = None,
                     admin: AdminUser = Depends(admin_access), db: AsyncSession = Depends(get_db)):
    conditions = [RedemptionCode.site_id == await site_scope(db, request, admin)]
    now = datetime.now(timezone.utc)
    if status == "expired":
        conditions += [RedemptionCode.status == "unused", RedemptionCode.expires_at <= now]
    elif status:
        conditions.append(RedemptionCode.status == status)
        if status == "unused":
            conditions.append((RedemptionCode.expires_at.is_(None)) | (RedemptionCode.expires_at > now))
    if batch_id:
        conditions.append(RedemptionCode.batch_id == str(batch_id))
    total = await db.scalar(select(func.count()).select_from(RedemptionCode).where(*conditions))
    rows = await db.scalars(select(RedemptionCode).where(*conditions)
                            .order_by(RedemptionCode.created_at.desc(), RedemptionCode.id)
                            .offset((page - 1) * page_size).limit(page_size))
    return ApiResponse.ok({"items": [code_out(row) for row in rows], "total": total})


@router.post("/{code_id}/disable")
async def disable_code(code_id: UUID, request: Request, admin: AdminUser = Depends(admin_access),
                       db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(RedemptionCode).where(
        RedemptionCode.id == str(code_id), RedemptionCode.site_id == await site_scope(db, request, admin)
    ).with_for_update())
    if row is None:
        raise AppException(code=40400, message="兑换码不存在", status_code=404)
    if row.status not in {"unused", "disabled"}:
        raise AppException(code=40900, message="已兑换或处理中的兑换码不可停用", status_code=409)
    row.status = "disabled"
    audit(db, admin, "redemption.disable", row.id, f"site={row.site_id}")
    await db.commit()
    return ApiResponse.ok(code_out(row))
