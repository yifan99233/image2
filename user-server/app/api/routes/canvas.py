import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field, JsonValue, model_validator
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.responses import ok
from app.db.session import get_db
from app.models.canvas import CanvasProject
from app.models.user import User

router = APIRouter(prefix="/canvas/projects", tags=["canvas"])
ProjectId = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class SaveCanvasRequest(BaseModel):
    revision: int = Field(ge=0)
    mutation_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    document: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_document(self):
        nodes = self.document.get("nodes")
        connections = self.document.get("connections")
        if not isinstance(nodes, list) or not isinstance(connections, list):
            raise ValueError("画布必须包含节点和连线列表")
        if len(nodes) > settings.canvas_max_nodes:
            raise ValueError("画布节点数量超过上限")
        ids = [node.get("id") for node in nodes if isinstance(node, dict)]
        if len(ids) != len(nodes) or any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("画布节点 ID 无效或重复")
        # Blob URLs only exist in one browser session and cannot be cloud state.
        def check_media(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"content", "url", "dataUrl"} and isinstance(child, str) and child.startswith(("blob:", "data:image/")):
                        raise ValueError("请先完成图片上传再保存画布")
                    check_media(child)
            elif isinstance(value, list):
                for child in value:
                    check_media(child)
        check_media(nodes)
        try:
            encoded = json.dumps(self.document, ensure_ascii=False, allow_nan=False).encode()
        except ValueError as exc:
            raise ValueError("画布包含无效数值") from exc
        if len(encoded) > settings.canvas_max_document_bytes:
            raise ValueError("画布文档超过大小上限，请拆分画布")
        return self


def scope(user: User):
    return (CanvasProject.site_id == user.site_id, CanvasProject.user_id == user.id)


def serialize(project: CanvasProject, *, include_document=True):
    data = {"id": project.id, "title": project.title, "revision": project.revision,
            "node_count": project.node_count, "connection_count": project.connection_count,
            "created_at": project.created_at.isoformat(), "updated_at": project.updated_at.isoformat()}
    if include_document:
        data["document"] = project.document
    return data


@router.get("")
async def list_projects(
    limit: int = Query(default=20, ge=1, le=100),
    before_created_at: datetime | None = None,
    before_id: str | None = Query(default=None, max_length=64),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    filters = [*scope(user), CanvasProject.deleted_at.is_(None)]
    if before_created_at is not None and before_id:
        filters.append(or_(CanvasProject.created_at < before_created_at,
                           and_(CanvasProject.created_at == before_created_at, CanvasProject.id < before_id)))
    rows = list((await db.scalars(select(CanvasProject).options(defer(CanvasProject.document)).where(*filters)
        .order_by(CanvasProject.created_at.desc(), CanvasProject.id.desc()).limit(limit + 1))).all())
    return ok({"items": [serialize(row, include_document=False) for row in rows[:limit]], "has_more": len(rows) > limit})


@router.get("/{project_id}")
async def get_project(project_id: ProjectId, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await db.scalar(select(CanvasProject).where(*scope(user), CanvasProject.id == project_id, CanvasProject.deleted_at.is_(None)))
    if project is None:
        raise BusinessError("画布不存在或已删除", code=40440, status_code=404)
    return ok(serialize(project))


@router.put("/{project_id}")
async def save_project(project_id: ProjectId, payload: SaveCanvasRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    values = {"title": payload.title.strip() or "未命名画布", "document": payload.document,
              "node_count": len(payload.document["nodes"]), "connection_count": len(payload.document["connections"]),
              "mutation_id": payload.mutation_id, "updated_at": func.now()}
    if payload.revision == 0:
        statement = insert(CanvasProject).values(**values, site_id=user.site_id, user_id=user.id, id=project_id, revision=1)
        result = await db.execute(statement.on_conflict_do_nothing().returning(CanvasProject.id))
    else:
        result = await db.execute(update(CanvasProject).where(*scope(user), CanvasProject.id == project_id,
            CanvasProject.revision == payload.revision, CanvasProject.deleted_at.is_(None))
            .values(**values, revision=payload.revision + 1).returning(CanvasProject.id))
    changed = result.scalar_one_or_none()
    project = await db.scalar(select(CanvasProject).where(*scope(user), CanvasProject.id == project_id))
    if changed is None and (project is None or project.deleted_at is not None or project.mutation_id != payload.mutation_id
                            or project.document != payload.document or project.title != values["title"]):
        await db.rollback()
        raise BusinessError("画布已在另一页面修改或删除。请导出当前画布备份，再重新加载；本次未覆盖云端版本。", code=40940, status_code=409)
    await db.commit()
    return ok(serialize(project))


@router.delete("/{project_id}")
async def delete_project(project_id: ProjectId, revision: int = Query(ge=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(update(CanvasProject).where(*scope(user), CanvasProject.id == project_id,
        CanvasProject.revision == revision, CanvasProject.deleted_at.is_(None))
        .values(deleted_at=func.now(), updated_at=func.now(), revision=CanvasProject.revision + 1).returning(CanvasProject.id))
    if result.scalar_one_or_none() is None:
        project = await db.scalar(select(CanvasProject).where(*scope(user), CanvasProject.id == project_id))
        if project is not None and project.deleted_at is None:
            await db.rollback()
            raise BusinessError("画布已被修改，请刷新后再删除", code=40940, status_code=409)
    await db.commit()
    return ok(None)
