import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.exceptions import AppException
from app.models.admin_openapi_key import AdminOpenAPIKey
from app.services.site_scope import current_site_id

OPENAPI_KEY_PREFIX = "iaoak"
OPENAPI_SCOPES = {
    "openagent:upload-token",
    "openagent:release:write",
}


def hash_openapi_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_openapi_key() -> tuple[str, str, str]:
    raw_key = f"{OPENAPI_KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    return raw_key, raw_key[:18], hash_openapi_key(raw_key)


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    requested = [str(scope).strip() for scope in scopes or [] if str(scope).strip()]
    if not requested:
        return ["openagent:upload-token", "openagent:release:write"]
    unknown = [scope for scope in requested if scope not in OPENAPI_SCOPES]
    if unknown:
        raise AppException(code=40001, message=f"未知 OpenAPI 权限：{', '.join(unknown)}", status_code=400)
    return list(dict.fromkeys(requested))


def key_scopes(api_key: AdminOpenAPIKey) -> set[str]:
    try:
        value = json.loads(api_key.scopes or "[]")
    except json.JSONDecodeError:
        value = []
    return {str(scope).strip() for scope in value if str(scope).strip()}


def openapi_key_out(api_key: AdminOpenAPIKey, *, plain_key: str | None = None) -> dict:
    return {
        "id": api_key.id,
        "site_id": api_key.site_id,
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "api_key": plain_key,
        "scopes": sorted(key_scopes(api_key)),
        "is_active": api_key.is_active,
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "updated_at": api_key.updated_at.isoformat() if api_key.updated_at else None,
    }


async def get_current_openapi_key(
    request: Request,
    x_admin_openapi_key: str | None = Header(default=None, alias="X-Admin-OpenAPI-Key"),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AdminOpenAPIKey:
    raw_key = (x_admin_openapi_key or "").strip()
    if not raw_key and authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization.split(" ", 1)[1].strip()
    if not raw_key:
        raise AppException(code=40100, message="缺少 OpenAPI Key", status_code=401)

    hashed = hash_openapi_key(raw_key)
    api_key = await db.scalar(select(AdminOpenAPIKey).where(AdminOpenAPIKey.key_hash == hashed))
    if api_key is None or not hmac.compare_digest(api_key.key_hash, hashed):
        raise AppException(code=40100, message="OpenAPI Key 无效", status_code=401)
    if not api_key.is_active:
        raise AppException(code=40300, message="OpenAPI Key 已停用", status_code=403)
    site_id = await current_site_id(db, request)
    if int(api_key.site_id or 1) != site_id:
        raise AppException(code=40300, message="OpenAPI Key 无权访问当前站点", status_code=403)
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return api_key


def require_openapi_scope(scope: str):
    async def dependency(api_key: AdminOpenAPIKey = Depends(get_current_openapi_key)) -> AdminOpenAPIKey:
        if scope not in key_scopes(api_key):
            raise AppException(code=40300, message="OpenAPI Key 权限不足", status_code=403)
        return api_key

    return dependency
