from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Boolean, Column, MetaData, String, Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.core.exceptions import BusinessError
from app.models.image_asset import ImageAsset
from app.models.user import User
from app.schemas.uploads import ImageAssetOut
from app.services.image_uploads import (
    effective_asset_url,
    prepare_r2_upload,
    save_uploaded_image,
    save_uploaded_r2_image,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])

# Keep this route independent from catalog.py (which imports upload services),
# while reading the existing model CDN/storage switch.
image_models_table = Table(
    "image_models",
    MetaData(),
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("storage_mode", String),
    Column("is_active", Boolean),
)


class R2UploadPrepareRequest(BaseModel):
    filename: str = Field(default="image.png", min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0)


class R2UploadCompleteRequest(BaseModel):
    object_key: str = Field(min_length=1, max_length=1024)
    completion_token: str = Field(min_length=16, max_length=512)
    content_type: str = Field(default="image/png", min_length=1, max_length=128)


def to_image_asset_out(asset) -> ImageAssetOut:
    r2_url = (asset.r2_url or "").strip() or None
    local_url = (asset.local_url or asset.url or "").strip() or None
    return ImageAssetOut(
        id=asset.id,
        url=effective_asset_url(asset),
        local_url=local_url,
        r2_url=r2_url,
        r2_expires_at=asset.r2_expires_at.isoformat() if asset.r2_expires_at else None,
        mime_type=asset.mime_type,
        width=asset.width,
        height=asset.height,
        size_bytes=asset.size_bytes,
        sha256=asset.sha256,
        source=asset.source,
    )


@router.post("/images", response_model=StandardResponse[ImageAssetOut])
async def upload_image(
    image: UploadFile = File(...),
    model_id: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StandardResponse[ImageAssetOut]:
    qiniu_storage_enabled: bool | None = None
    if model_id is not None:
        model_row = (
            await db.execute(
                select(image_models_table.c.storage_mode).where(
                    image_models_table.c.id == model_id,
                    image_models_table.c.site_id == current_user.site_id,
                    image_models_table.c.is_active.is_(True),
                )
            )
        ).first()
        if model_row is None:
            raise BusinessError("模型不存在或当前站点不可用", code=40430, status_code=404)
        storage_mode = str(model_row[0] or "").strip().lower()
        if storage_mode == "third_party":
            qiniu_storage_enabled = True
        elif storage_mode == "local":
            qiniu_storage_enabled = False

    asset = await save_uploaded_image(
        db=db,
        current_user=current_user,
        upload=image,
        qiniu_storage_enabled=qiniu_storage_enabled,
    )
    return ok(to_image_asset_out(asset), "上传成功")


@router.post("/images/r2/presign", response_model=StandardResponse[dict])
async def presign_r2_image_upload(
    payload: R2UploadPrepareRequest,
    current_user: User = Depends(get_current_user),
) -> StandardResponse[dict]:
    return ok(
        prepare_r2_upload(
            user_id=int(current_user.id),
            filename=payload.filename,
            mime_type=payload.content_type,
            size_bytes=payload.size_bytes,
        )
    )


@router.post("/images/r2/complete", response_model=StandardResponse[ImageAssetOut])
async def complete_r2_image_upload(
    payload: R2UploadCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StandardResponse[ImageAssetOut]:
    asset = await save_uploaded_r2_image(
        db=db,
        current_user=current_user,
        object_key=payload.object_key,
        completion_token=payload.completion_token,
        submitted_mime_type=payload.content_type,
    )
    return ok(to_image_asset_out(asset), "上传成功")


@router.get("/images/{asset_id}/signed-url", response_model=StandardResponse[dict])
async def signed_image_url(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StandardResponse[dict]:
    asset = await db.scalar(select(ImageAsset).where(ImageAsset.id == asset_id, ImageAsset.site_id == current_user.site_id, ImageAsset.user_id == current_user.id))
    if asset is None:
        raise BusinessError("图片不存在或无权访问", code=40420, status_code=404)
    return ok(
        {
            "url": effective_asset_url(asset),
            "local_url": asset.local_url or asset.url,
            "r2_url": asset.r2_url,
            "r2_expires_at": asset.r2_expires_at.isoformat() if asset.r2_expires_at else None,
        }
    )
