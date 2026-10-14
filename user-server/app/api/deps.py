from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.db.session import get_db
from app.models.user import User
from app.services.security import verify_access_token
from app.services.site_scope import current_site_id


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise BusinessError("未授权：缺少凭证", code=40100, status_code=401)
    payload = verify_access_token(authorization.split(" ", 1)[1])
    subject = payload.get("sub")
    if not subject:
        raise BusinessError("令牌载荷无效", code=40101, status_code=401)
    try:
        user_id = int(subject)
    except ValueError as exc:
        raise BusinessError("令牌载荷无效", code=40101, status_code=401) from exc
    site_id = await current_site_id(db, request)
    user = await db.scalar(select(User).where(User.id == user_id, User.site_id == site_id, User.deleted_at.is_(None)))
    if user is None:
        raise BusinessError("用户不存在或已注销", code=40102, status_code=401)
    if not user.is_active:
        raise BusinessError("账户已被禁用", code=40103, status_code=401)
    return user
