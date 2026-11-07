import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Column, DateTime, MetaData, String, Table, Text, desc, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.image_asset import ImageAsset
from app.models.user import User

router = APIRouter(prefix="/feedbacks", tags=["feedbacks"])

shared_metadata = MetaData()
feedbacks_table = Table(
    "user_feedbacks",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("description", Text),
    Column("image_urls", Text),
    Column("status", String),
    Column("admin_remark", Text),
    Column("handled_by", BigInteger),
    Column("handled_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)


class FeedbackCreateRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    image_asset_ids: list[int] = Field(default_factory=list, max_length=4)


def feedback_out(row) -> dict:
    try:
        image_urls = json.loads(row.image_urls or "[]")
    except json.JSONDecodeError:
        image_urls = []
    return {
        "id": row.id,
        "description": row.description,
        "image_urls": image_urls if isinstance(image_urls, list) else [],
        "status": row.status or "pending",
        "admin_remark": row.admin_remark or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("", response_model=StandardResponse[dict])
async def create_feedback(
    payload: FeedbackCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StandardResponse[dict]:
    description = payload.description.strip()
    if not description:
        raise BusinessError("请填写反馈描述", code=40030)
    if len(payload.image_asset_ids) > 4:
        raise BusinessError("反馈图片最多 4 张", code=40031)

    image_urls: list[str] = []
    if payload.image_asset_ids:
        unique_ids = list(dict.fromkeys(payload.image_asset_ids))
        if len(unique_ids) != len(payload.image_asset_ids):
            raise BusinessError("反馈图片不能重复选择", code=40032)
        result = await db.execute(
            select(ImageAsset.id, ImageAsset.url)
            .where(ImageAsset.site_id == current_user.site_id, ImageAsset.user_id == current_user.id, ImageAsset.id.in_(unique_ids))
        )
        assets = {row.id: row.url for row in result}
        missing_ids = [asset_id for asset_id in unique_ids if asset_id not in assets]
        if missing_ids:
            raise BusinessError("反馈图片不存在或无权使用", code=40430, status_code=404)
        image_urls = [assets[asset_id] for asset_id in unique_ids]

    now = datetime.now(UTC)
    result = await db.execute(
        insert(feedbacks_table)
        .values(
            user_id=current_user.id,
            site_id=current_user.site_id,
            description=description,
            image_urls=json.dumps(image_urls, ensure_ascii=False),
            status="pending",
            admin_remark="",
            created_at=now,
            updated_at=now,
        )
        .returning(feedbacks_table)
    )
    await db.commit()
    return ok(feedback_out(result.mappings().first()), "反馈已提交")


@router.get("", response_model=StandardResponse[dict])
async def my_feedbacks(
    page_no: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StandardResponse[dict]:
    condition = (feedbacks_table.c.user_id == current_user.id) & (feedbacks_table.c.site_id == current_user.site_id)
    total = await db.scalar(select(func.count()).select_from(feedbacks_table).where(condition))
    result = await db.execute(
        select(feedbacks_table)
        .where(condition)
        .order_by(desc(feedbacks_table.c.created_at), desc(feedbacks_table.c.id))
        .offset((page_no - 1) * page_size)
        .limit(page_size)
    )
    items = [feedback_out(row) for row in result.mappings().all()]
    return ok({"items": items, "total": total or 0, "page": page_no, "page_size": page_size})
