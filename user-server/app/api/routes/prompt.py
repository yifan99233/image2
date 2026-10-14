import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import case, desc, func, outerjoin, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.catalog import generation_model_config, image_models_table, image_tasks_table, model_supports_work_type, visible_task_condition
from app.api.routes.ux import get_max_batch_tasks
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.user import User
from app.services.document_extract import extract_document
from app.services.text_generation import build_agent_plan, optimize_prompt, stream_optimized_prompt

router = APIRouter(prefix="/prompt", tags=["prompt"])
logger = logging.getLogger(__name__)
MAX_DOCUMENT_PLAN_PROMPTS = 100


def resolve_agent_plan_prompt_limit(*, requested: int, batch_limit: int, has_document: bool) -> int:
    normalized_requested = max(1, requested)
    if has_document:
        return min(normalized_requested, MAX_DOCUMENT_PLAN_PROMPTS)
    return min(normalized_requested, batch_limit)


async def _resolve_own_creation_history(db: AsyncSession, current_user: User, query: object) -> str:
    payload = query if isinstance(query, dict) else {}
    mode = str(payload.get("mode") or "summary")
    try:
        range_hours = int(payload.get("range_hours")) if payload.get("range_hours") is not None else None
    except (TypeError, ValueError):
        range_hours = None
    if range_hours is not None:
        range_hours = min(max(range_hours, 1), 24 * 365)

    # Keep Agent history exactly aligned with the direct task feed, including
    # the same site/team visibility and soft-delete filtering rules.
    scope = [await visible_task_condition(db, current_user)]
    range_label = "全部历史"
    if range_hours is not None:
        scope.append(image_tasks_table.c.created_at >= datetime.now(UTC) - timedelta(hours=range_hours))
        range_label = f"最近 {range_hours} 小时"

    if mode == "latest":
        row = (
            await db.execute(
                select(
                    image_tasks_table.c.prompt,
                    image_tasks_table.c.status,
                    image_tasks_table.c.work_type,
                    image_tasks_table.c.created_at,
                    image_models_table.c.name.label("model_name"),
                )
                .select_from(outerjoin(image_tasks_table, image_models_table, image_tasks_table.c.model_id == image_models_table.c.id))
                .where(*scope)
                .order_by(desc(image_tasks_table.c.created_at), desc(image_tasks_table.c.id))
                .limit(1)
            )
        ).first()
        if row is None:
            return f"{range_label}暂无创作记录。"
        kind = "视频" if "video" in str(row.work_type or "").lower() else "图片"
        return f"最近一次{kind}创作：{row.prompt or '未填写提示词'}。模型：{row.model_name or '未知模型'}，状态：{row.status or '未知'}。"

    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.coalesce(func.sum(case((image_tasks_table.c.status == "succeeded", 1), else_=0)), 0).label("succeeded"),
                func.coalesce(func.sum(case((image_tasks_table.c.status.in_(("failed", "refunded")), 1), else_=0)), 0).label("failed"),
                func.coalesce(func.sum(case((image_tasks_table.c.work_type.ilike("%video%"), 1), else_=0)), 0).label("videos"),
            ).where(*scope)
        )
    ).one()
    total = int(row.total or 0)
    succeeded = int(row.succeeded or 0)
    failed = int(row.failed or 0)
    return f"【创作汇总 · {range_label}】共 {total} 条，完成 {succeeded} 条，失败 {failed} 条，图片 {total - int(row.videos or 0)} 条，视频 {int(row.videos or 0)} 条。"


async def _load_text_model(db: AsyncSession, current_user: User, model_id: int):
    if not model_id:
        raise BusinessError("请选择文本模型", code=40051)
    row = (
        await db.execute(
            select(
                image_models_table.c.id,
                image_models_table.c.work_type,
                image_models_table.c.is_active,
                image_models_table.c.is_public,
            ).where(
                image_models_table.c.id == model_id,
                image_models_table.c.site_id == current_user.site_id,
            )
        )
    ).first()
    if row is None or not row.is_active or not model_supports_work_type(row.work_type, ["text"]):
        raise BusinessError("文本模型不可用", code=40452, status_code=404)
    if not row.is_public and not bool(getattr(current_user, "is_internal", False)):
        raise BusinessError("文本模型不可用", code=40452, status_code=404)
    return await generation_model_config(db, model_id, current_user.site_id)


@router.post("/optimize", response_model=StandardResponse[dict])
async def optimize(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    prompt = str(payload.get("prompt") or "").strip()
    model_id = int(payload.get("model_id") or 0)
    if not prompt:
        raise BusinessError("请输入需要优化的提示词", code=40050)
    config = await _load_text_model(db, current_user, model_id)
    media = str(payload.get("media") or "image").strip().lower()
    if media not in {"image", "video"}:
        media = "image"
    has_images = bool(payload.get("has_images"))
    optimized = optimize_prompt(config, prompt, media=media, has_images=has_images)
    return ok({"prompt": optimized, "media": media, "has_images": has_images})


@router.post("/optimize/stream")
async def optimize_stream(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    prompt = str(payload.get("prompt") or "").strip()
    model_id = int(payload.get("model_id") or 0)
    if not prompt:
        raise BusinessError("请输入需要优化的提示词", code=40050)
    config = await _load_text_model(db, current_user, model_id)
    media = str(payload.get("media") or "image").strip().lower()
    if media not in {"image", "video"}:
        media = "image"
    has_images = bool(payload.get("has_images"))

    def event_stream():
        for event in stream_optimized_prompt(config, prompt, media=media, has_images=has_images):
            event_type = str(event.get("type") or "message")
            yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/extract-document", response_model=StandardResponse[dict])
async def extract_document_route(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> StandardResponse[dict]:
    _ = current_user
    content = await file.read()
    extracted = extract_document(
        filename=file.filename or "document",
        content=content,
        content_type=file.content_type,
    )
    return ok(
        {
            "name": extracted.name,
            "mime_type": extracted.mime_type,
            "text": extracted.text,
            "char_count": extracted.char_count,
        }
    )


@router.post("/agent-plan", response_model=StandardResponse[dict])
async def agent_plan(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    model_id = int(payload.get("model_id") or 0)
    user_prompt = str(payload.get("prompt") or "").strip()
    document_text = str(payload.get("document_text") or "").strip()
    session_context = str(payload.get("session_context") or "").strip()
    if not user_prompt and not document_text:
        raise BusinessError("请输入创作意图或上传文档", code=40060)
    config = await _load_text_model(db, current_user, model_id)
    media = str(payload.get("media") or "image").strip().lower()
    if media not in {"image", "video"}:
        media = "image"
    has_images = bool(payload.get("has_images"))
    requested_max_prompts = int(payload.get("max_prompts") or 1)
    max_prompts = resolve_agent_plan_prompt_limit(
        requested=requested_max_prompts,
        batch_limit=await get_max_batch_tasks(db, current_user.site_id),
        has_document=bool(document_text),
    )
    available_models = payload.get("available_models") or payload.get("models") or []
    if not isinstance(available_models, list):
        available_models = []

    # Release the connection used for model/config lookups before the long-running
    # external Agent call.  The same session can reacquire a connection later if
    # the completed plan needs a history lookup.
    await db.rollback()
    plan = await asyncio.to_thread(
        build_agent_plan,
        config,
        user_prompt=user_prompt,
        session_context=session_context,
        document_text=document_text,
        media=media,
        has_images=has_images,
        max_prompts=max_prompts,
        available_models=available_models,
    )
    logger.info(
        "agent_plan user_id=%s intent=%s document=%s document_mode=%s prompt_count=%s task_count=%s source=%s",
        current_user.id,
        plan.get("intent"),
        bool(document_text),
        plan.get("document_mode"),
        len(plan.get("prompts") or []),
        plan.get("task_count"),
        plan.get("source"),
    )
    if plan.get("intent") == "query_own_creation_history":
        plan["history_reply"] = await _resolve_own_creation_history(db, current_user, plan.get("history_query"))
    return ok(plan)


@router.post("/agent-plan/stream")
async def agent_plan_stream(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    model_id = int(payload.get("model_id") or 0)
    user_prompt = str(payload.get("prompt") or "").strip()
    document_text = str(payload.get("document_text") or "").strip()
    session_context = str(payload.get("session_context") or "").strip()
    if not user_prompt and not document_text:
        raise BusinessError("请输入创作意图或上传文档", code=40060)
    config = await _load_text_model(db, current_user, model_id)
    media = str(payload.get("media") or "image").strip().lower()
    if media not in {"image", "video"}:
        media = "image"
    requested_max_prompts = int(payload.get("max_prompts") or 1)
    max_prompts = resolve_agent_plan_prompt_limit(
        requested=requested_max_prompts,
        batch_limit=await get_max_batch_tasks(db, current_user.site_id),
        has_document=bool(document_text),
    )
    available_models = payload.get("available_models") or payload.get("models") or []
    if not isinstance(available_models, list):
        available_models = []

    # Release the connection used for model/config lookups before the
    # long-running external Agent call. The same session can reacquire a
    # connection later if the completed plan needs a history lookup.
    await db.rollback()

    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[str] = asyncio.Queue()

    def report(message: str) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, message)

    async def build_plan() -> dict:
        return await asyncio.to_thread(
            build_agent_plan,
            config,
            user_prompt=user_prompt,
            session_context=session_context,
            document_text=document_text,
            media=media,
            has_images=bool(payload.get("has_images")),
            max_prompts=max_prompts,
            available_models=available_models,
            on_progress=report,
        )

    task = asyncio.create_task(build_plan())

    async def events():
        try:
            yield f"event: status\ndata: {json.dumps({'message': 'Agent 正在开始规划…'}, ensure_ascii=False)}\n\n"
            while not task.done():
                try:
                    message = await asyncio.wait_for(progress_queue.get(), timeout=12)
                    yield f"event: status\ndata: {json.dumps({'message': message}, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield f"event: status\ndata: {json.dumps({'message': 'Agent 仍在处理文档…'}, ensure_ascii=False)}\n\n"
            try:
                plan = task.result()
                if plan.get("intent") == "query_own_creation_history":
                    plan["history_reply"] = await _resolve_own_creation_history(db, current_user, plan.get("history_query"))
                logger.info(
                    "agent_plan_stream user_id=%s intent=%s document=%s prompt_count=%s",
                    current_user.id,
                    plan.get("intent"),
                    bool(document_text),
                    len(plan.get("prompts") or []),
                )
                yield f"event: complete\ndata: {json.dumps({'plan': plan}, ensure_ascii=False)}\n\n"
            except BusinessError as exc:
                yield f"event: error\ndata: {json.dumps({'message': exc.message}, ensure_ascii=False)}\n\n"
            except Exception:
                logger.exception("agent_plan_stream_failed user_id=%s", current_user.id)
                yield f"event: error\ndata: {json.dumps({'message': 'Agent 规划失败，请稍后重试'}, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
