from collections.abc import AsyncGenerator, Callable

from fastapi import Depends, Header, Request
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.session import AsyncSessionLocal
from app.models.admin_user import AdminRole, AdminUser
from app.services.security import verify_admin_token
from app.services.site_scope import current_site_id


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_admin(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppException(code=40100, message="未授权：缺少凭证", status_code=401)

    token = authorization.split(" ", 1)[1]
    try:
        payload = verify_admin_token(token)
    except JWTError:
        raise AppException(code=40100, message="未授权：令牌无效", status_code=401) from None

    admin_id = payload.get("sub")
    if not admin_id:
        raise AppException(code=40100, message="未授权：令牌载荷无效", status_code=401)

    try:
        uid = int(admin_id)
    except ValueError:
        raise AppException(code=40100, message="未授权：管理员 ID 无效", status_code=401) from None

    admin = await db.scalar(select(AdminUser).where(AdminUser.id == uid))
    if admin is None:
        raise AppException(code=40100, message="未授权：管理员不存在", status_code=401)
    if not admin.is_active:
        raise AppException(code=40100, message="未授权：管理员已禁用", status_code=401)
    site_id = await current_site_id(db, request)
    if not admin.system_super_admin and int(admin.site_id or 1) != site_id:
        raise AppException(code=40300, message="无权限访问当前站点后台", status_code=403)
    return admin


def require_admin_roles(*roles: AdminRole) -> Callable[[AdminUser], AdminUser]:
    allowed = set(roles)

    async def dependency(current_admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
        if current_admin.system_super_admin or current_admin.role in allowed:
            return current_admin
        raise AppException(code=40300, message="无权限访问", status_code=403)

    return dependency


async def require_system_super_admin(current_admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if current_admin.system_super_admin:
        return current_admin
    raise AppException(code=40300, message="需要系统超级管理员权限", status_code=403)
