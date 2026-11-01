"""Browser/CDN exports: metadata and XLSX only; never fetch image bytes."""
import tempfile
from pathlib import Path
from typing import Literal

from anyio import to_thread
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api.deps import get_current_user
from app.api.routes import catalog
from app.api.routes.catalog_exports import ExportItem, _safe_filename_part, export_limiter
from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.responses import ok
from app.db.session import get_db
from app.models.user import User
from app.services.batch_export_reports import BatchExportReports, validate_folder_name

router = APIRouter(tags=["browser exports"])


def folder_and_stem(row):
    folder = row.input_group_name or "生成结果"
    try:
        validate_folder_name(folder)
    except BusinessError:
        folder = _safe_filename_part(folder, fallback="生成结果")
    return folder, f"{int(row.id):08d}-{_safe_filename_part(row.task_no, fallback='task')}"


async def conditions(db, user, batch_id):
    tasks = catalog.image_tasks_table
    return [await catalog.visible_task_condition(db, user), tasks.c.batch_id == batch_id,
            tasks.c.work_type == "batch_generate"]


@router.get("/image-tasks/browser-export/items")
async def export_items(batch_id: str = Query(min_length=1, max_length=64),
                       after_id: int = Query(default=0, ge=0), max_id: int | None = Query(default=None, ge=1),
                       limit: int = Query(default=200, ge=1, le=200),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tasks = catalog.image_tasks_table
    filters = await conditions(db, user, batch_id)
    if max_id is None:
        max_id = await db.scalar(select(func.max(tasks.c.id)).where(*filters))
    if not max_id:
        raise BusinessError("没有可导出的任务", code=40033)
    total = await db.scalar(select(func.count()).select_from(tasks).where(*filters, tasks.c.id <= max_id))
    if not total or total > catalog.MAX_BATCH_GENERATE_COUNT:
        raise BusinessError("批次不存在或超过单次下载上限", code=40043)
    rows = (await db.execute(select(tasks.c.id, tasks.c.task_no, tasks.c.input_group_name,
                                   tasks.c.output_image_url, tasks.c.output_expired_at, tasks.c.status, tasks.c.failure_message)
                            .where(*filters, tasks.c.id > after_id, tasks.c.id <= max_id)
                            .order_by(tasks.c.id).limit(limit + 1))).all()
    items = []
    for row in rows[:limit]:
        folder, stem = folder_and_stem(row)
        items.append({"id": row.id, "folder": folder, "stem": stem, "url": "" if row.output_expired_at else (row.output_image_url or ""),
                      "status": row.status, "error": "图片已过期" if row.output_expired_at else (row.failure_message or "")})
    return ok({"items": items, "max_id": max_id, "total": total, "has_more": len(rows) > limit,
               "next_cursor": items[-1]["id"] if items else after_id,
               "max_image_bytes": settings.image_result_download_max_bytes})


class DownloadResult(BaseModel):
    id: int = Field(gt=0, strict=True)
    status: Literal["成功", "失败", "未完成"]
    extension: Literal["", ".png", ".jpg", ".webp", ".gif", ".avif", ".bmp"] = ""
    error: str = Field(default="", max_length=512)


class ReportRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=64)
    results: list[DownloadResult] = Field(min_length=1, max_length=20000)


@router.post("/image-tasks/browser-export/reports/{kind}")
async def export_report(kind: Literal["full", "failed"], payload: ReportRequest,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ids = [result.id for result in payload.results]
    if len(set(ids)) != len(ids) or ids != sorted(ids):
        raise BusinessError("下载结果序号无效", code=40043)
    tasks = catalog.image_tasks_table
    rows = (await db.execute(select(tasks.c.id, tasks.c.task_no, tasks.c.prompt, tasks.c.input_group_name,
                                   tasks.c.status)
                            .where(*(await conditions(db, user, payload.batch_id)), tasks.c.id.in_(ids))
                            .order_by(tasks.c.id))).all()
    if [row.id for row in rows] != ids:
        raise BusinessError("部分任务不存在或无权导出", code=40301, status_code=403)
    for row, result in zip(rows, payload.results):
        if result.status == "成功" and (row.status != "succeeded" or not result.extension):
            raise BusinessError("下载结果与任务状态不一致", code=40043)
    await db.rollback()
    directory = tempfile.TemporaryDirectory(prefix="browser-export-reports-")
    filename = "完整汇总.xlsx" if kind == "full" else "失败汇总.xlsx"

    def build():
        reports = BatchExportReports(directory.name, max(1, max((len(row.prompt or "") + 29999) // 30000 for row in rows)))
        try:
            for index, (row, result) in enumerate(zip(rows, payload.results), 1):
                folder, stem = folder_and_stem(row)
                item = ExportItem(row.task_no, "", prompt=row.prompt or "")
                reports.append(index, item, folder, f"{folder}/{stem}{result.extension}" if result.status == "成功" else "",
                               result.status, result.error)
        finally:
            reports.close()

    try:
        await to_thread.run_sync(build, limiter=export_limiter)
    except BaseException:
        directory.cleanup()
        raise
    return FileResponse(Path(directory.name) / filename, filename=filename,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Cache-Control": "no-store"}, background=BackgroundTask(directory.cleanup))
