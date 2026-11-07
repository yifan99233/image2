from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_db, require_admin_roles
from app.core.exceptions import AppException
from app.models.admin_user import AdminRole, AdminUser
from app.schemas.auth import AdminLoginRequest, AdminLoginResponse, AdminUserOut, ChangePasswordRequest
from app.schemas.response import ApiResponse
from app.services.rsa import decrypt_password_if_needed, get_public_key_pem
from app.services.security import hash_password, issue_admin_token, verify_password
from app.services.site_scope import current_site_id

router = APIRouter()


@router.get("/public-key", response_model=ApiResponse[str])
async def public_key() -> ApiResponse[str]:
    return ApiResponse.ok(get_public_key_pem())


@router.post("/login", response_model=ApiResponse[AdminLoginResponse])
async def login(payload: AdminLoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> ApiResponse[AdminLoginResponse]:
    password = decrypt_password_if_needed(payload.password)
    admin = await db.scalar(select(AdminUser).where(AdminUser.username == payload.username))

    if admin is None or not verify_password(password, admin.password_hash):
        raise AppException(code=40101, message="用户名或密码错误", status_code=401)
    if not admin.is_active:
        raise AppException(code=40301, message="管理员已禁用", status_code=403)
    site_id = await current_site_id(db, request)
    if not admin.system_super_admin and int(admin.site_id or 1) != site_id:
        raise AppException(code=40300, message="无权限登录当前站点后台", status_code=403)

    admin.last_login_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(admin)

    token = issue_admin_token(admin)
    return ApiResponse.ok(AdminLoginResponse(access_token=token, admin=AdminUserOut.model_validate(admin)))


@router.get("/me", response_model=ApiResponse[AdminUserOut])
async def me(current_admin: AdminUser = Depends(get_current_admin)) -> ApiResponse[AdminUserOut]:
    return ApiResponse.ok(AdminUserOut.model_validate(current_admin))


@router.patch("/me/password", response_model=ApiResponse[dict])
async def change_password(
    payload: ChangePasswordRequest,
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance, AdminRole.model_admin)),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    old_password = decrypt_password_if_needed(payload.old_password)
    new_password = decrypt_password_if_needed(payload.new_password)

    if not verify_password(old_password, current_admin.password_hash):
        raise AppException(code=40001, message="原密码不正确", status_code=400)

    current_admin.password_hash = hash_password(new_password)
    await db.commit()
    return ApiResponse.ok({"changed": True})
