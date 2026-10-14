import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Column, DateTime, MetaData, String, Table, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.uploads import to_image_asset_out
from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.image_asset import ImageAsset
from app.models.user import User
from app.services.image_thumbnails import get_or_create_thumbnail, is_valid_thumbnail_token, thumbnail_token
from app.services.image_uploads import save_uploaded_image
from app.services.material_billing import debit_material_cdn_upload, refund_material_cdn_upload
from app.services.team_sharing import get_primary_team_id, material_library_is_shared

router = APIRouter(prefix="/materials", tags=["materials"])
material_thumbnail_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="material-thumbnail")
material_thumbnail_inflight = asyncio.Semaphore(2)


class MaterialAssetLink(BaseModel):
    asset_id: int = Field(gt=0)
    name: str = Field(default="", max_length=160)


class LinkMaterialAssetsRequest(BaseModel):
    assets: list[MaterialAssetLink] = Field(min_length=1, max_length=50)
    folder_id: int | None = None


def normalize_upload_mode(value: str | None) -> str:
    mode = (value or "local").strip().lower()
    if mode not in {"local", "cdn"}:
        raise BusinessError("素材上传方式无效", code=40043)
    return mode

metadata = MetaData()
material_folders_table = Table(
    "user_material_folders",
    metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("team_id", BigInteger),
    Column("user_id", BigInteger),
    Column("parent_id", BigInteger),
    Column("name", String),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
material_assets_table = Table(
    "user_material_assets",
    metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("team_id", BigInteger),
    Column("user_id", BigInteger),
    Column("folder_id", BigInteger),
    Column("image_asset_id", BigInteger),
    Column("name", String),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)


def normalize_parent_id(value: int | None) -> int | None:
    return int(value) if value and int(value) > 0 else None


def normalize_name(value: str, fallback: str) -> str:
    name = value.strip()
    if not name:
        name = fallback
    return name[:160]


def require_name(value: str, message: str) -> str:
    name = value.strip()
    if not name:
        raise BusinessError(message, code=40042)
    return name[:160]


def active_team_material_condition(table, current_user: User, team_id: int, material_library_shared: bool):
    if not material_library_shared:
        return and_(
            table.c.user_id == current_user.id,
            or_(table.c.team_id == team_id, table.c.team_id.is_(None)),
        )
    return or_(
        table.c.team_id == team_id,
        and_(table.c.team_id.is_(None), table.c.user_id == current_user.id),
    )


async def ensure_folder(db: AsyncSession, current_user: User, folder_id: int | None) -> int | None:
    folder_id = normalize_parent_id(folder_id)
    if folder_id is None:
        return None
    team_id = await get_primary_team_id(db, current_user)
    material_shared = await material_library_is_shared(db, current_user)
    row = (
        await db.execute(
            select(material_folders_table.c.id).where(
                material_folders_table.c.id == folder_id,
                material_folders_table.c.site_id == current_user.site_id,
                active_team_material_condition(material_folders_table, current_user, team_id, material_shared),
            )
        )
    ).first()
    if row is None:
        raise BusinessError("目录不存在或无权访问", code=40440, status_code=404)
    return folder_id


def folder_out(row) -> dict:
    return {
        "id": row.id,
        "parent_id": row.parent_id,
        "name": row.name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def material_out(row) -> dict:
    asset = ImageAsset(
        id=row.image_asset_id,
        url=row.url,
        local_url=row.local_url,
        r2_url=row.r2_url,
        r2_expires_at=row.r2_expires_at,
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        source=row.source,
    )
    asset_payload = to_image_asset_out(asset).model_dump()
    source_url = (asset.local_url or asset.url or "").strip()
    if source_url:
        asset_payload["thumbnail_url"] = material_thumbnail_url(int(row.id), source_url)
    return {
        "id": row.id,
        "folder_id": row.folder_id,
        "name": row.name,
        "asset": asset_payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def material_thumbnail_url(material_id: int, source_url: str) -> str:
    token = thumbnail_token(material_id, source_url)
    return f"/materials/assets/{material_id}/thumbnail?token={token}"


@router.get("", response_model=StandardResponse[dict])
async def list_materials(
    folder_id: int | None = None,
    keyword: str = "",
    page_no: int = 1,
    page_size: int = 40,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    folder_id = normalize_parent_id(folder_id)
    page_no = max(1, page_no)
    page_size = min(max(1, page_size), 80)
    team_id = await get_primary_team_id(db, current_user)
    material_shared = await material_library_is_shared(db, current_user)
    folder_condition = material_assets_table.c.folder_id.is_(None) if folder_id is None else material_assets_table.c.folder_id == folder_id
    condition = and_(
        material_assets_table.c.site_id == current_user.site_id,
        active_team_material_condition(material_assets_table, current_user, team_id, material_shared),
        folder_condition,
    )
    if keyword.strip():
        condition = and_(condition, material_assets_table.c.name.ilike(f"%{keyword.strip()}%"))
    joined = material_assets_table.join(ImageAsset.__table__, material_assets_table.c.image_asset_id == ImageAsset.id)
    total = await db.scalar(select(func.count()).select_from(joined).where(condition))
    rows = (
        await db.execute(
            select(
                material_assets_table.c.id,
                material_assets_table.c.folder_id,
                material_assets_table.c.name,
                material_assets_table.c.created_at,
                material_assets_table.c.updated_at,
                ImageAsset.id.label("image_asset_id"),
                ImageAsset.url,
                ImageAsset.local_url,
                ImageAsset.r2_url,
                ImageAsset.r2_expires_at,
                ImageAsset.mime_type,
                ImageAsset.width,
                ImageAsset.height,
                ImageAsset.size_bytes,
                ImageAsset.sha256,
                ImageAsset.source,
            )
            .select_from(joined)
            .where(condition)
            .order_by(material_assets_table.c.created_at.desc(), material_assets_table.c.id.desc())
            .offset((page_no - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ok({"items": [material_out(row) for row in rows], "page": page_no, "page_size": page_size, "total": total or 0})


@router.get("/folders", response_model=StandardResponse[list])
async def list_folders(
    parent_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    parent_id = normalize_parent_id(parent_id)
    team_id = await get_primary_team_id(db, current_user)
    material_shared = await material_library_is_shared(db, current_user)
    parent_condition = material_folders_table.c.parent_id.is_(None) if parent_id is None else material_folders_table.c.parent_id == parent_id
    rows = (
        await db.execute(
            select(material_folders_table)
            .where(
                material_folders_table.c.site_id == current_user.site_id,
                active_team_material_condition(material_folders_table, current_user, team_id, material_shared),
                parent_condition,
            )
            .order_by(material_folders_table.c.created_at.asc(), material_folders_table.c.id.asc())
        )
    ).all()
    return ok([folder_out(row) for row in rows])


@router.get("/assets/{material_id}/thumbnail", response_class=Response)
async def material_thumbnail(
    material_id: int,
    token: str = Query(min_length=16, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(
            select(material_assets_table.c.image_asset_id, ImageAsset.url, ImageAsset.local_url)
            .select_from(material_assets_table.join(ImageAsset.__table__, material_assets_table.c.image_asset_id == ImageAsset.id))
            .where(material_assets_table.c.id == material_id)
        )
    ).first()
    source_url = str((row.local_url or row.url) if row else "").strip()
    if not source_url or not is_valid_thumbnail_token(material_id, source_url, token):
        raise BusinessError("缩略图不存在", code=40441, status_code=404)
    async with material_thumbnail_inflight:
        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(
            material_thumbnail_executor,
            lambda: get_or_create_thumbnail(material_id, source_url),
        )
    return Response(
        content=content,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": f'inline; filename="material-{material_id}-thumbnail.webp"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/folders", response_model=StandardResponse[dict])
async def create_folder(payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    parent_id = await ensure_folder(db, current_user, payload.get("parent_id"))
    team_id = await get_primary_team_id(db, current_user)
    material_shared = await material_library_is_shared(db, current_user)
    name = require_name(str(payload.get("name") or ""), "请输入目录名称")
    result = await db.execute(
        material_folders_table.insert()
        .values(
            site_id=current_user.site_id,
            team_id=team_id,
            user_id=current_user.id,
            parent_id=parent_id,
            name=name,
        )
        .returning(material_folders_table.c.id)
    )
    folder_id = result.scalar_one()
    await db.commit()
    row = (await db.execute(select(material_folders_table).where(material_folders_table.c.id == folder_id))).first()
    return ok(folder_out(row), "目录已创建")


@router.patch("/folders/{folder_id}", response_model=StandardResponse[dict])
async def update_folder(folder_id: int, payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    await ensure_folder(db, current_user, folder_id)
    name = normalize_name(str(payload.get("name") or ""), "未命名目录")
    team_id = await get_primary_team_id(db, current_user)
    await db.execute(
        update(material_folders_table)
        .where(
            material_folders_table.c.id == folder_id,
            material_folders_table.c.site_id == current_user.site_id,
            active_team_material_condition(material_folders_table, current_user, team_id, material_shared),
        )
        .values(name=name, updated_at=func.now())
    )
    await db.commit()
    row = (await db.execute(select(material_folders_table).where(material_folders_table.c.id == folder_id))).first()
    return ok(folder_out(row), "目录已更新")


@router.get("/upload-options", response_model=StandardResponse[dict])
async def material_upload_options(current_user: User = Depends(get_current_user)) -> StandardResponse[dict]:
    return ok(
        {
            "default_mode": "local",
            "cdn_credit_cost": settings.material_cdn_upload_credit_cost,
        }
    )


@router.post("/assets", response_model=StandardResponse[list])
async def upload_material_assets(
    images: Annotated[list[UploadFile], File(...)],
    folder_id: Annotated[int | None, Form()] = None,
    upload_mode: Annotated[str, Form()] = "local",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    upload_mode = normalize_upload_mode(upload_mode)
    use_cdn = upload_mode == "cdn"
    folder_id = await ensure_folder(db, current_user, folder_id)
    team_id = await get_primary_team_id(db, current_user)
    material_shared = await material_library_is_shared(db, current_user)
    created_ids: list[int] = []
    for upload in images[:50]:
        charge_receipt = None
        try:
            if use_cdn:
                charge_receipt = await debit_material_cdn_upload(
                    db,
                    user_id=current_user.id,
                    credit_amount=settings.material_cdn_upload_credit_cost,
                )
                await db.commit()
            asset = await save_uploaded_image(
                db=db,
                current_user=current_user,
                upload=upload,
                qiniu_storage_enabled=use_cdn,
            )
            fallback_name = Path(upload.filename or "").stem or f"素材 {asset.id}"
            result = await db.execute(
                material_assets_table.insert()
                .values(
                    site_id=current_user.site_id,
                    team_id=team_id,
                    user_id=current_user.id,
                    folder_id=folder_id,
                    image_asset_id=asset.id,
                    name=normalize_name(fallback_name, f"素材 {asset.id}"),
                )
                .returning(material_assets_table.c.id)
            )
            material_id = result.scalar_one()
            await db.commit()
            created_ids.append(material_id)
        except Exception:
            await db.rollback()
            if charge_receipt is not None:
                await refund_material_cdn_upload(
                    db,
                    user_id=current_user.id,
                    receipt=charge_receipt,
                )
                await db.commit()
            raise
    if not created_ids:
        raise BusinessError("请选择要上传的图片", code=40041)
    rows = (
        await db.execute(
            select(
                material_assets_table.c.id,
                material_assets_table.c.folder_id,
                material_assets_table.c.name,
                material_assets_table.c.created_at,
                material_assets_table.c.updated_at,
                ImageAsset.id.label("image_asset_id"),
                ImageAsset.url,
                ImageAsset.local_url,
                ImageAsset.r2_url,
                ImageAsset.r2_expires_at,
                ImageAsset.mime_type,
                ImageAsset.width,
                ImageAsset.height,
                ImageAsset.size_bytes,
                ImageAsset.sha256,
                ImageAsset.source,
            )
            .select_from(material_assets_table.join(ImageAsset.__table__, material_assets_table.c.image_asset_id == ImageAsset.id))
            .where(material_assets_table.c.id.in_(created_ids))
            .order_by(material_assets_table.c.id.asc())
        )
    ).all()
    return ok([material_out(row) for row in rows], "素材已上传")


@router.post("/assets/link", response_model=StandardResponse[list])
async def link_uploaded_material_assets(
    payload: LinkMaterialAssetsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    folder_id = await ensure_folder(db, current_user, payload.folder_id)
    team_id = await get_primary_team_id(db, current_user)
    asset_ids = list(dict.fromkeys(item.asset_id for item in payload.assets))
    owned_assets = (
        await db.execute(
            select(ImageAsset.id).where(
                ImageAsset.id.in_(asset_ids),
                ImageAsset.site_id == current_user.site_id,
                ImageAsset.user_id == current_user.id,
            )
        )
    ).scalars().all()
    owned_ids = {int(asset_id) for asset_id in owned_assets}
    if len(owned_ids) != len(asset_ids):
        raise BusinessError("包含不存在的素材图片", code=40420, status_code=404)

    material_ids: list[int] = []
    name_by_id = {item.asset_id: item.name for item in payload.assets}
    for asset_id in asset_ids:
        result = await db.execute(
            material_assets_table.insert()
            .values(
                site_id=current_user.site_id,
                team_id=team_id,
                user_id=current_user.id,
                folder_id=folder_id,
                image_asset_id=asset_id,
                name=normalize_name(name_by_id.get(asset_id) or "", f"素材 {asset_id}"),
            )
            .returning(material_assets_table.c.id)
        )
        material_ids.append(int(result.scalar_one()))
    await db.commit()
    rows = (
        await db.execute(
            select(
                material_assets_table.c.id,
                material_assets_table.c.folder_id,
                material_assets_table.c.name,
                material_assets_table.c.created_at,
                material_assets_table.c.updated_at,
                ImageAsset.id.label("image_asset_id"),
                ImageAsset.url,
                ImageAsset.local_url,
                ImageAsset.r2_url,
                ImageAsset.r2_expires_at,
                ImageAsset.mime_type,
                ImageAsset.width,
                ImageAsset.height,
                ImageAsset.size_bytes,
                ImageAsset.sha256,
                ImageAsset.source,
            )
            .select_from(material_assets_table.join(ImageAsset.__table__, material_assets_table.c.image_asset_id == ImageAsset.id))
            .where(material_assets_table.c.id.in_(material_ids))
            .order_by(material_assets_table.c.id.asc())
        )
    ).all()
    return ok([material_out(row) for row in rows], "素材已上传")


@router.patch("/assets/{material_id}", response_model=StandardResponse[dict])
async def update_material_asset(material_id: int, payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    folder_id = await ensure_folder(db, current_user, payload.get("folder_id"))
    team_id = await get_primary_team_id(db, current_user)
    name = normalize_name(str(payload.get("name") or ""), "未命名素材")
    result = await db.execute(
        update(material_assets_table)
        .where(
            material_assets_table.c.id == material_id,
            material_assets_table.c.site_id == current_user.site_id,
            active_team_material_condition(material_assets_table, current_user, team_id, material_shared),
        )
        .values(name=name, folder_id=folder_id, updated_at=func.now())
    )
    if result.rowcount == 0:
        raise BusinessError("素材不存在或无权访问", code=40441, status_code=404)
    await db.commit()
    row = (
        await db.execute(
            select(
                material_assets_table.c.id,
                material_assets_table.c.folder_id,
                material_assets_table.c.name,
                material_assets_table.c.created_at,
                material_assets_table.c.updated_at,
                ImageAsset.id.label("image_asset_id"),
                ImageAsset.url,
                ImageAsset.local_url,
                ImageAsset.r2_url,
                ImageAsset.r2_expires_at,
                ImageAsset.mime_type,
                ImageAsset.width,
                ImageAsset.height,
                ImageAsset.size_bytes,
                ImageAsset.sha256,
                ImageAsset.source,
            )
            .select_from(material_assets_table.join(ImageAsset.__table__, material_assets_table.c.image_asset_id == ImageAsset.id))
            .where(material_assets_table.c.id == material_id)
        )
    ).first()
    return ok(material_out(row), "素材已更新")
