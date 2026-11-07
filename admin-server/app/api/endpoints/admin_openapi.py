from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.endpoints.admin_data import (
    OpenAgentReleaseRequest,
    OpenAgentUploadTokenRequest,
    add_audit,
    normalize_openagent_filename,
    openagent_release_out,
    qiniu_upload_token,
)
from app.core.config import settings
from app.models.admin_openapi_key import AdminOpenAPIKey
from app.models.openagent_release import OpenAgentRelease
from app.schemas.response import ApiResponse
from app.services.admin_openapi import require_openapi_scope

router = APIRouter(prefix="/openapi/admin", tags=["admin-openapi"])


@router.post("/openagent/upload-token", response_model=ApiResponse[dict])
async def openagent_upload_token(
    payload: OpenAgentUploadTokenRequest,
    api_key: AdminOpenAPIKey = Depends(require_openapi_scope("openagent:upload-token")),
) -> ApiResponse[dict]:
    filename = normalize_openagent_filename(payload.filename)
    key = f"{settings.openagent_release_prefix.strip().strip('/')}/site-{api_key.site_id}/{filename}"
    cdn_base = settings.qiniu_cdn_base_url.rstrip("/")
    return ApiResponse.ok(
        {
            "upload_url": settings.qiniu_upload_host.rstrip("/"),
            "token": qiniu_upload_token(key),
            "key": key,
            "public_url": f"{cdn_base}/{key}",
        }
    )


@router.post("/openagent/releases", response_model=ApiResponse[dict])
async def save_openagent_release(
    payload: OpenAgentReleaseRequest,
    db: AsyncSession = Depends(get_db),
    api_key: AdminOpenAPIKey = Depends(require_openapi_scope("openagent:release:write")),
) -> ApiResponse[dict]:
    release = await db.scalar(
        select(OpenAgentRelease).where(
            OpenAgentRelease.site_id == api_key.site_id,
            OpenAgentRelease.channel == payload.channel,
            OpenAgentRelease.version == payload.version.strip(),
            OpenAgentRelease.platform == payload.platform,
            OpenAgentRelease.arch == payload.arch,
        )
    )
    now = datetime.now(timezone.utc)
    if release is None:
        release = OpenAgentRelease(
            site_id=api_key.site_id,
            channel=payload.channel,
            version=payload.version.strip(),
            platform=payload.platform,
            arch=payload.arch,
            created_by=None,
            published_at=now if payload.is_active else None,
        )
        db.add(release)
        action = "openapi_create_openagent_release"
    else:
        action = "openapi_update_openagent_release"

    release.file_url = payload.file_url.strip()
    release.file_sha512 = payload.file_sha512.strip()
    release.file_size = payload.file_size
    release.release_notes = payload.release_notes.strip() or None
    release.is_active = payload.is_active
    release.is_mandatory = payload.is_mandatory
    if payload.is_active and release.published_at is None:
        release.published_at = now
    release.updated_at = now
    await db.flush()
    add_audit(db, None, action, "openagent_releases", release.id, f"openapi_key={api_key.id}; {release.channel}/{release.arch} {release.version}")
    await db.commit()
    await db.refresh(release)
    return ApiResponse.ok(openagent_release_out(release), "OpenAgent 更新版本已保存")
