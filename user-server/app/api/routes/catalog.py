import asyncio
import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from time import perf_counter
from typing import Annotated
from uuid import UUID, uuid4
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, Numeric, String, Table, Text, and_, delete, desc, func, or_, outerjoin, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.batch_groups import MAX_GROUPED_OUTPUTS, validate_batch_groups
from app.api.routes.catalog_exports import ExportItem, build_export_archive, stream_export_archive
from app.api.routes.catalog_serializers import USER_IMAGE_TASK_FAILURE_MESSAGE, output_assets_from_row, canonicalize_asset_url, input_urls_from_row, serialize_gallery_work, serialize_task, serialize_task_status, serialize_user_work
from app.api.routes.ux import get_max_batch_tasks, get_qiniu_storage_enabled
from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import AsyncSessionLocal, get_db
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.user import User
from app.models.image_asset import ImageAsset
from app.services.customer_pricing import customer_price
from app.services.asset_urls import asset_url_variants
from app.services.image_generation import (
    DEFAULT_MODEL_TASK_TIMEOUT_SECONDS,
    MAX_MODEL_TASK_TIMEOUT_SECONDS,
    MIN_MODEL_TASK_TIMEOUT_SECONDS,
    MODEL_TIMEOUT_CODE,
    MODEL_TIMEOUT_MESSAGE,
    RESULT_DOWNLOAD_TIMEOUT_CODE,
    GenerationModelConfig,
    GeneratedImage,
    generate_image,
    image_output_capabilities,
    validate_image_output_options,
    generate_video,
    pack_video_task_aspect,
    resume_video_job,
    unpack_video_task_aspect,
)
from app.services.image_parameters import DEFAULT_IMAGE_QUALITY, normalize_image_quality, image_output_options
from app.services.image_provider_models import images_per_generation, is_banana_images_model
from app.services.image_uploads import (
    create_generated_image_asset,
    store_generated_image_object,
    store_native_generated_object,
)
from app.services.image_thumbnails import get_or_create_thumbnail, is_valid_thumbnail_token
from app.services.sub2_image_billing import Sub2BalanceReceipt, debit_image_task_balance, refund_image_task_balance
from app.services.team_sharing import get_primary_team_id, image_history_is_shared
from app.services.security import create_export_access_token, verify_export_access_token

router = APIRouter(tags=["catalog"])
model_queue_lock = asyncio.Lock()
image_task_dispatcher_event = asyncio.Event()
image_task_dispatcher_tasks: set[asyncio.Task] = set()
image_task_dispatcher_tasks_lock = asyncio.Lock()
ACTIVE_IMAGE_TASK_STATUSES = ("pending", "queued", "running")
MAX_TASK_STATUS_BATCH_SIZE = 200
MAX_STANDARD_OUTPUT_COUNT = 9
MAX_BATCH_GENERATE_COUNT = 20000
MAX_BATCH_EDIT_TASKS = 200
MAX_EXPORT_TASK_IDS = 5000
MAX_BATCH_PROMPT_CHARS = 1_000_000
IMAGE_TASK_DISPATCHER_ADVISORY_LOCK_KEY = 0x5A4F4244
STALE_IMAGE_TASK_FAILURE_MESSAGE = "任务执行超时，系统已自动回收并退回积分"
MODEL_TASK_TIMEOUT_FAILURE_MESSAGE = "模型执行超时，系统已自动退回积分"
logger = logging.getLogger(__name__)
image_generation_executor = ThreadPoolExecutor(
    max_workers=max(1, settings.image_task_generation_thread_pool_size),
    thread_name_prefix="image-generation",
)
image_storage_executor = ThreadPoolExecutor(
    max_workers=max(1, settings.image_task_storage_thread_pool_size),
    thread_name_prefix="image-storage",
)
image_thumbnail_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="image-thumbnail")
image_thumbnail_inflight = asyncio.Semaphore(2)
# 限制同时打上游的生成并发，避免大批量任务把排队时间混进 upstream_generate
image_generation_inflight = asyncio.Semaphore(max(1, settings.image_task_generation_max_inflight))


class ImageTaskStatusesRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=MAX_TASK_STATUS_BATCH_SIZE)


async def _persist_video_job_id(task_id: int, job_id: str, snapshot: dict | None = None) -> None:
    async with AsyncSessionLocal() as db:
        saved = await mark_image_task_provider_job(
            db,
            task_id,
            provider_request_id=job_id,
            provider_request_snapshot=snapshot,
        )
        if saved:
            logger.warning(
                "image_task_provider_job_saved task_id=%s provider_request_id=%s",
                task_id,
                job_id,
            )


async def _persist_image_model_completed(task_id: int, trace) -> bool:
    async with AsyncSessionLocal() as db:
        values = {
            "provider_request_id": trace.provider_request_id or None,
            "provider_request_snapshot": (
                json.dumps(trace.provider_request_snapshot, ensure_ascii=False)
                if trace.provider_request_snapshot
                else None
            ),
            "provider_response_summary": (
                json.dumps(trace.provider_response_summary, ensure_ascii=False)
                if trace.provider_response_summary
                else None
            ),
            # 回调只会在成功收到模型响应后触发；无响应头状态时使用成功哨兵，
            # 让回收器准确识别“模型已完成、正在同步结果”的边界。
            "provider_http_status": trace.provider_http_status or 200,
            "worker_heartbeat_at": datetime.now(UTC),
        }
        result = await db.execute(
            update(image_tasks_table)
            .where(
                image_tasks_table.c.id == task_id,
                image_tasks_table.c.status == "running",
            )
            .values(**values)
            .returning(image_tasks_table.c.id)
        )
        await db.commit()
        return result.first() is not None


async def _persist_image_model_started(task_id: int, timeout_seconds: int) -> datetime | None:
    started_at = datetime.now(UTC)
    deadline_at = task_deadline_at(started_at, timeout_seconds)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(image_tasks_table)
            .where(
                image_tasks_table.c.id == task_id,
                image_tasks_table.c.status == "running",
                image_tasks_table.c.provider_http_status.is_(None),
            )
            .values(
                deadline_at=deadline_at,
                worker_started_at=func.coalesce(image_tasks_table.c.worker_started_at, started_at),
                worker_heartbeat_at=started_at,
            )
            .returning(image_tasks_table.c.id)
        )
        await db.commit()
        return deadline_at if result.first() is not None else None


async def run_image_generation_in_executor(
    config: GenerationModelConfig,
    prompt: str,
    input_image: str | list[str] | None,
    resolution: str,
    aspect_ratio: str,
    quality: str = DEFAULT_IMAGE_QUALITY,
    *,
    size: str | None = None,
    output_format: str | None = None,
    task_no: str = "",
    task_id: int | None = None,
    user_id: int | None = None,
    attempt: int = 1,
    media_kind: str = "image",
) -> tuple:
    """跑 generate_image / generate_video，返回 (GeneratedImage, timing_dict)。

    timing_dict 含 slot_wait / executor_wait / generate，避免排队被误当成上游慢。
    """
    loop = asyncio.get_running_loop()
    slot_wait_started = perf_counter()
    async with image_generation_inflight:
        slot_wait_secs = perf_counter() - slot_wait_started
        if slot_wait_secs >= 0.05:
            logger.warning(
                "image_task_timing stage=generation_slot_wait task_no=%s task_id=%s attempt=%s elapsed=%.3fs max_inflight=%s",
                task_no or "-",
                task_id if task_id is not None else "-",
                attempt,
                slot_wait_secs,
                settings.image_task_generation_max_inflight,
            )

        submit_started = perf_counter()

        model_stage = {"completed": False}

        def _job():
            thread_acquired = perf_counter()
            if media_kind == "video":
                video_ratio, video_duration = unpack_video_task_aspect(aspect_ratio)

                def _on_job_created(job_id: str, snapshot: dict) -> None:
                    if task_id is None:
                        return
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            _persist_video_job_id(int(task_id), job_id, snapshot),
                            loop,
                        )
                        future.result(timeout=8)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "persist_video_job_id_failed task_id=%s job_id=%s",
                            task_id,
                            job_id,
                        )

                image = generate_video(
                    config,
                    prompt,
                    input_image,
                    resolution,
                    duration=video_duration,
                    aspect_ratio=video_ratio,
                    user=str(user_id or ""),
                    on_job_created=_on_job_created if task_id is not None else None,
                )
            else:
                def _on_model_started() -> None:
                    if task_id is None:
                        return
                    future = asyncio.run_coroutine_threadsafe(
                        _persist_image_model_started(int(task_id), config.timeout_seconds),
                        loop,
                    )
                    persisted_deadline = future.result(timeout=15)
                    if persisted_deadline is None:
                        raise BusinessError("任务状态已变化，停止模型请求", code=40912, status_code=409)

                def _on_model_completed(trace) -> None:
                    if task_id is None:
                        model_stage["completed"] = True
                        return
                    future = asyncio.run_coroutine_threadsafe(
                        _persist_image_model_completed(int(task_id), trace),
                        loop,
                    )
                    saved = future.result(timeout=15)
                    if not saved:
                        raise BusinessError("任务状态已变化，停止同步模型结果", code=40912, status_code=409)
                    model_stage["completed"] = True

                callback_kwargs = (
                    {
                        "on_model_started": _on_model_started,
                        "on_model_completed": _on_model_completed,
                    }
                    if task_id is not None
                    else {}
                )
                image = generate_image(
                    config,
                    prompt,
                    input_image,
                    resolution,
                    aspect_ratio,
                    quality=quality,
                    **image_output_options({"size": size, "output_format": output_format}),
                    client_reference=task_no,
                    **callback_kwargs,
                )
            return image, thread_acquired

        image, thread_acquired = await loop.run_in_executor(image_generation_executor, _job)
        executor_wait_secs = max(0.0, thread_acquired - submit_started)
        generate_secs = max(0.0, perf_counter() - thread_acquired)
        timing = {
            "slot_wait_secs": round(slot_wait_secs, 3),
            "executor_wait_secs": round(executor_wait_secs, 3),
            "generate_secs": round(generate_secs, 3),
            "model_completed": bool(model_stage["completed"]),
        }
        if executor_wait_secs >= 0.05 or generate_secs >= 0.05:
            logger.warning(
                "image_task_timing stage=generation_breakdown task_no=%s task_id=%s attempt=%s "
                "slot_wait=%.3fs executor_wait=%.3fs generate=%.3fs",
                task_no or "-",
                task_id if task_id is not None else "-",
                attempt,
                slot_wait_secs,
                executor_wait_secs,
                generate_secs,
            )
        return image, timing


async def run_generated_image_storage_in_executor(
    *,
    user_id: int,
    content: bytes,
    mime_type: str,
    qiniu_storage_enabled: bool | None = None,
    storage_mode: str = "local",
    source_url: str | None = None,
    hot_url: str | None = None,
) -> dict:
    loop = asyncio.get_running_loop()
    mode = normalize_storage_mode(storage_mode)
    if mode == "native" and not hot_url:
        if not source_url:
            raise BusinessError("原生存储缺少媒体链接", code=50032, status_code=500)
        return await loop.run_in_executor(
            image_storage_executor,
            lambda: store_native_generated_object(
                user_id=user_id,
                source_url=source_url,
                mime_type=mime_type,
            ),
        )
    forced_qiniu = True if mode == "third_party" else False if mode == "local" else qiniu_storage_enabled
    return await loop.run_in_executor(
        image_storage_executor,
        lambda: store_generated_image_object(
            user_id=user_id,
            content=content,
            mime_type=mime_type,
            qiniu_storage_enabled=forced_qiniu,
            hot_url=hot_url,
        ),
    )

shared_metadata = MetaData()
image_models_table = Table(
    "image_models",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("provider_id", BigInteger),
    Column("name", String),
    Column("code", String),
    Column("vendor_model", String),
    Column("work_type", String),
    Column("capability_type", String),
    Column("description", String),
    Column("is_recommended", Boolean),
    Column("is_stable", Boolean),
    Column("is_new", Boolean),
    Column("speed_hint", String),
    Column("risk_hint", String),
    Column("max_input_images", Integer),
    Column("max_output_images", Integer),
    Column("concurrency_limit", Integer),
    Column("sort_order", Integer),
    Column("is_active", Boolean),
    Column("is_public", Boolean),
    Column("storage_mode", String),
    Column("timeout_seconds", Integer),
    Column("disable_retry", Boolean),
)
image_model_providers_table = Table(
    "image_model_providers",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("name", String),
    Column("code", String),
    Column("base_url", String),
    Column("access_mode", String),
    Column("auth_type", String),
    Column("encrypted_api_key", String),
    Column("timeout_seconds", Integer),
    Column("is_active", Boolean),
)
image_resolution_specs_table = Table(
    "image_resolution_specs",
    shared_metadata,
    Column("id", BigInteger),
    Column("code", String),
    Column("label", String),
    Column("sort_order", Integer),
    Column("is_active", Boolean),
)
image_aspect_ratio_specs_table = Table(
    "image_aspect_ratio_specs",
    shared_metadata,
    Column("id", BigInteger),
    Column("code", String),
    Column("label", String),
    Column("sort_order", Integer),
    Column("is_active", Boolean),
)
image_model_resolutions_table = Table(
    "image_model_resolutions",
    shared_metadata,
    Column("model_id", BigInteger),
    Column("resolution_id", BigInteger),
)
image_model_aspect_ratios_table = Table(
    "image_model_aspect_ratios",
    shared_metadata,
    Column("model_id", BigInteger),
    Column("aspect_ratio_id", BigInteger),
)
video_duration_specs_table = Table(
    "video_duration_specs",
    shared_metadata,
    Column("id", BigInteger),
    Column("code", String),
    Column("label", String),
    Column("sort_order", Integer),
    Column("is_active", Boolean),
)
image_model_durations_table = Table(
    "image_model_durations",
    shared_metadata,
    Column("model_id", BigInteger),
    Column("duration_id", BigInteger),
)
image_assets_table = Table(
    "image_assets",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("url", String),
    Column("local_url", String),
    Column("r2_url", String),
    Column("r2_expires_at", DateTime(timezone=True)),
)
image_tasks_table = Table(
    "image_tasks",
    shared_metadata,
    Column("id", BigInteger),
    Column("task_no", String),
    Column("batch_id", String),
    Column("input_group_id", String),
    Column("input_group_name", String),
    Column("input_group_path", String),
    Column("batch_request_hash", String),
    Column("retry_of_task_id", BigInteger),
    Column("retry_of_batch_id", String),
    Column("site_id", BigInteger),
    Column("team_id", BigInteger),
    Column("user_id", BigInteger),
    Column("model_id", BigInteger),
    Column("work_type", String),
    Column("prompt", Text),
    Column("resolution", String),
    Column("aspect_ratio", String),
    Column("quality", String),
    Column("size", String),
    Column("output_format", String),
    Column("credit_cost", Numeric(20, 2)),
    Column("pricing_snapshot", JSONB),
    Column("status", String),
    Column("failure_message", Text),
    Column("input_image_url", String),
    Column("input_image_urls", Text),
    Column("output_image_url", String),
    Column("output_image_assets", JSONB),
    Column("output_expired_at", DateTime(timezone=True)),
    Column("output_image_r2_url", String),
    Column("output_image_r2_expires_at", DateTime(timezone=True)),
    Column("is_collected", Boolean),
    Column("is_gallery_featured", Boolean),
    Column("gallery_featured_by", BigInteger),
    Column("gallery_title", String),
    Column("gallery_sort_order", Integer),
    Column("gallery_featured_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("worker_started_at", DateTime(timezone=True)),
    Column("worker_heartbeat_at", DateTime(timezone=True)),
    Column("provider_request_id", String),
    Column("provider_request_snapshot", Text),
    Column("provider_response_summary", Text),
    Column("provider_http_status", Integer),
    Column("timeout_seconds", Integer),
    Column("disable_retry", Boolean),
    Column("deadline_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),
)
users_table = Table(
    "users",
    shared_metadata,
    Column("id", BigInteger),
    Column("username", String),
    Column("nickname", String),
)
image_model_prices_table = Table(
    "image_model_prices",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("model_id", BigInteger),
    Column("work_type", String),
    Column("resolution", String),
    Column("aspect_ratio", String),
    Column("output_count", Integer),
    Column("credit_cost", Integer),
    Column("fixed_surcharge", Numeric(20, 2)),
    Column("quality", String),
    Column("version", Integer),
    Column("is_active", Boolean),
    Column("effective_at", DateTime(timezone=True)),
)


def requested_work_types(work_type: str) -> list[str]:
    normalized = work_type.strip()
    if normalized == "image_edit":
        return ["image_to_image", "image_edit"]
    if normalized == "batch_generate":
        return ["text_to_image"]
    if normalized == "batch_edit":
        return ["image_to_image", "image_edit"]
    if normalized == "prompt_optimize":
        return ["text"]
    return [normalized]


def owner_name_expr():
    return func.coalesce(users_table.c.nickname, users_table.c.username, "").label("owner_name")


def task_join_with_owner():
    return outerjoin(
        outerjoin(image_tasks_table, image_models_table, image_tasks_table.c.model_id == image_models_table.c.id),
        users_table,
        image_tasks_table.c.user_id == users_table.c.id,
    )


async def visible_task_condition(db: AsyncSession, current_user: User):
    if await image_history_is_shared(db, current_user):
        team_id = await get_primary_team_id(db, current_user)
        return and_(
            image_tasks_table.c.site_id == current_user.site_id,
            image_tasks_table.c.deleted_at.is_(None),
            or_(
                image_tasks_table.c.team_id == team_id,
                and_(image_tasks_table.c.team_id.is_(None), image_tasks_table.c.user_id == current_user.id),
            ),
        )
    return and_(
        image_tasks_table.c.user_id == current_user.id,
        image_tasks_table.c.site_id == current_user.site_id,
        image_tasks_table.c.deleted_at.is_(None),
    )


def model_supports_work_type(model_work_type: str, work_types: list[str]) -> bool:
    supported = {part.strip() for part in model_work_type.split(",") if part.strip()}
    return bool(supported.intersection(work_types))


def dump_input_image_urls(urls: list[str]) -> str | None:
    if not urls:
        return None
    return json.dumps(urls, ensure_ascii=False)


async def resolve_input_image_urls(
    db: AsyncSession,
    *,
    site_id: int,
    user_id: int,
    payload: dict,
    max_input_images: int,
) -> list[str]:
    # Uploaded assets are identified by their database IDs. The web client also
    # sends their URLs so URL-only callers (such as the canvas) remain
    # supported, but a display/CDN URL is not authoritative when an owned ID is
    # present: its hostname can legitimately change between upload and submit.
    input_image_ids = [
        int(asset_id)
        for asset_id in payload.get("input_image_ids") or []
        if int(asset_id) > 0
    ]
    if len(input_image_ids) > max_input_images:
        raise BusinessError(code=40001, message=f"当前模型最多支持 {max_input_images} 张输入图")
    if input_image_ids:
        rows = await db.execute(
            select(image_assets_table.c.id, image_assets_table.c.url, image_assets_table.c.local_url).where(
                image_assets_table.c.id.in_(input_image_ids),
                image_assets_table.c.site_id == site_id,
                image_assets_table.c.user_id == user_id,
            )
        )
        url_by_id = {
            int(row.id): getattr(row, "url", None) or row.local_url
            for row in rows
            if getattr(row, "url", None) or row.local_url
        }
        missing_ids = [asset_id for asset_id in input_image_ids if asset_id not in url_by_id]
        if missing_ids:
            raise BusinessError(code=40420, message="包含不存在的输入图片", status_code=404)
        return [url_by_id[asset_id] for asset_id in input_image_ids]

    submitted_urls = [
        str(url).strip()
        for url in payload.get("input_image_urls") or []
        if str(url).strip()
    ]
    if not submitted_urls:
        submitted_input_image_url = str(payload.get("input_image_url") or "").strip()
        submitted_urls = [submitted_input_image_url] if submitted_input_image_url else []
    submitted_urls = list(dict.fromkeys(submitted_urls))
    if len(submitted_urls) > max_input_images:
        raise BusinessError(code=40001, message=f"当前模型最多支持 {max_input_images} 张输入图")
    if submitted_urls:
        lookup_urls = list(dict.fromkeys(
            variant for url in submitted_urls for variant in asset_url_variants(url)
        ))
        result = await db.execute(
            select(
                image_assets_table.c.url,
                image_assets_table.c.local_url,
                image_assets_table.c.r2_url,
            ).where(
                or_(
                    image_assets_table.c.url.in_(lookup_urls),
                    image_assets_table.c.local_url.in_(lookup_urls),
                    image_assets_table.c.r2_url.in_(lookup_urls),
                ),
                image_assets_table.c.site_id == site_id,
                image_assets_table.c.user_id == user_id,
            )
        )
        rows = result.all()
        owned_urls = {
            variant
            for row in rows
            for value in (
                getattr(row, "url", None),
                getattr(row, "local_url", None),
                getattr(row, "r2_url", None),
            )
            if value
            for variant in asset_url_variants(str(value))
        }
        missing_urls = [url for url in submitted_urls if url not in owned_urls]
        if missing_urls:
            raise BusinessError(code=40420, message="包含不存在的输入图片", status_code=404)
        browser_by_submitted_url = {
            variant: str(getattr(row, "url", None) or row.local_url)
            for row in rows
            for value in (
                getattr(row, "url", None),
                getattr(row, "local_url", None),
                getattr(row, "r2_url", None),
            )
            if value and (getattr(row, "url", None) or row.local_url)
            for variant in asset_url_variants(str(value))
        }
        return [browser_by_submitted_url[url] for url in submitted_urls]
    return []


async def get_or_create_credit_account_for_update(db: AsyncSession, user_id: int) -> UserCreditAccount:
    account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == user_id).with_for_update())
    if account is not None:
        return account
    account = UserCreditAccount(user_id=user_id)
    db.add(account)
    await db.flush()
    return account


def add_credit_ledger(
    *,
    db: AsyncSession,
    account: UserCreditAccount,
    user_id: int,
    direction: str,
    amount: int,
    balance_before: int,
    balance_after: int,
    biz_type: str,
    biz_id: str,
    idempotency_key: str,
    description: str,
    gift_amount: int = 0,
    operator_type: str = "user",
    operator_id: int | None = None,
) -> None:
    db.add(
        CreditLedger(
            user_id=user_id,
            account_id=account.id,
            direction=direction,
            gift_amount=gift_amount,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            biz_type=biz_type,
            biz_id=biz_id,
            idempotency_key=idempotency_key,
            description=description,
            operator_type=operator_type,
            operator_id=operator_id if operator_id is not None else (user_id if operator_type == "user" else None),
            created_at=datetime.now(UTC),
        )
    )


def is_missing_shared_table_error(error: Exception, table_name: str) -> bool:
    return table_name in str(error).lower()


async def debit_image_task_credits(
    db: AsyncSession,
    user_id: int,
    task_no: str,
    credit_cost: Decimal,
) -> Sub2BalanceReceipt | None:
    if credit_cost <= 0:
        return None
    sub2_receipt = await debit_image_task_balance(db, user_id=user_id, task_no=task_no, credit_amount=credit_cost)
    try:
        account = await get_or_create_credit_account_for_update(db, user_id)
        if sub2_receipt is None and account.balance < credit_cost:
            raise BusinessError("积分余额不足", code=40030)
        balance_before = account.balance
        balance_after = balance_before - credit_cost
        account.balance = balance_after
        gift_used = min(account.gift_balance, credit_cost)
        account.gift_balance -= gift_used
        account.total_consumed += credit_cost
        account.version += 1
        add_credit_ledger(
            db=db,
            account=account,
            user_id=user_id,
            direction="debit",
            amount=credit_cost,
            balance_before=balance_before,
            balance_after=balance_after,
            biz_type="image_task",
            gift_amount=gift_used,
            biz_id=task_no,
            idempotency_key=f"image-task:debit:{task_no}",
            description=f"图片任务预扣 {credit_cost} 积分",
        )
    except Exception:
        if sub2_receipt is not None:
            await compensate_image_task_creation_debits(db, [sub2_receipt])
        raise
    return sub2_receipt


async def refund_image_task_credits(db: AsyncSession, user_id: int, task_no: str, credit_cost: Decimal) -> None:
    if credit_cost <= 0:
        return
    refund_key = f"image-task:refund:{task_no}"
    existing_refund_id = await db.scalar(select(CreditLedger.id).where(CreditLedger.idempotency_key == refund_key))
    if existing_refund_id is not None:
        return
    await refund_image_task_balance(db, task_no=task_no)
    account = await get_or_create_credit_account_for_update(db, user_id)
    balance_before = account.balance
    balance_after = balance_before + credit_cost
    account.balance = balance_after
    gift_refund = await db.scalar(select(CreditLedger.gift_amount).where(
        CreditLedger.idempotency_key == f"image-task:debit:{task_no}"
    )) or 0
    account.gift_balance += gift_refund
    account.total_consumed = max(0, account.total_consumed - credit_cost)
    account.version += 1
    add_credit_ledger(
        db=db,
        account=account,
        user_id=user_id,
        direction="credit",
        amount=credit_cost,
        balance_before=balance_before,
        balance_after=balance_after,
        biz_type="refund",
        gift_amount=gift_refund,
        biz_id=task_no,
        idempotency_key=refund_key,
        description=f"图片任务失败返还 {credit_cost} 积分",
    )


async def compensate_image_task_creation_debits(
    db: AsyncSession,
    receipts: list[Sub2BalanceReceipt],
) -> None:
    await db.rollback()
    failed_task_numbers: list[str] = []
    for receipt in reversed(receipts):
        try:
            await refund_image_task_balance(db, task_no=receipt.biz_id, receipt=receipt)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            failed_task_numbers.append(receipt.biz_id)
            logger.exception("image_task_creation_refund_failed task_no=%s", receipt.biz_id)
    if failed_task_numbers:
        raise BusinessError("任务创建失败，账户退款未完成，请联系客服", code=50388, status_code=503)


async def model_options(db: AsyncSession, model_id: int) -> tuple[list[dict], list[dict], list[dict]]:
    resolutions = await db.execute(
        select(image_resolution_specs_table.c.code, image_resolution_specs_table.c.label)
        .select_from(
            image_model_resolutions_table.join(
                image_resolution_specs_table,
                image_model_resolutions_table.c.resolution_id == image_resolution_specs_table.c.id,
            )
        )
        .where(
            image_model_resolutions_table.c.model_id == model_id,
            image_resolution_specs_table.c.is_active.is_(True),
        )
        .order_by(image_resolution_specs_table.c.sort_order.asc(), image_resolution_specs_table.c.id.asc())
    )
    aspect_ratios = await db.execute(
        select(image_aspect_ratio_specs_table.c.code, image_aspect_ratio_specs_table.c.label)
        .select_from(
            image_model_aspect_ratios_table.join(
                image_aspect_ratio_specs_table,
                image_model_aspect_ratios_table.c.aspect_ratio_id == image_aspect_ratio_specs_table.c.id,
            )
        )
        .where(
            image_model_aspect_ratios_table.c.model_id == model_id,
            image_aspect_ratio_specs_table.c.is_active.is_(True),
        )
        .order_by(image_aspect_ratio_specs_table.c.sort_order.asc(), image_aspect_ratio_specs_table.c.id.asc())
    )
    durations = await db.execute(
        select(video_duration_specs_table.c.code, video_duration_specs_table.c.label)
        .select_from(
            image_model_durations_table.join(
                video_duration_specs_table,
                image_model_durations_table.c.duration_id == video_duration_specs_table.c.id,
            )
        )
        .where(
            image_model_durations_table.c.model_id == model_id,
            video_duration_specs_table.c.is_active.is_(True),
        )
        .order_by(video_duration_specs_table.c.sort_order.asc(), video_duration_specs_table.c.id.asc())
    )
    return (
        [{"value": row.code, "label": row.label} for row in resolutions],
        [{"value": row.code, "label": row.label} for row in aspect_ratios],
        [{"value": row.code, "label": row.label} for row in durations],
    )


def is_video_work_type(work_type: str | None) -> bool:
    normalized = (work_type or "").strip()
    if not normalized:
        return False
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    return bool(parts) and all(part in {"text_to_video", "image_to_video"} for part in parts)


DEFAULT_VIDEO_ASPECT_RATIOS = [
    {"value": "1:1", "label": "1:1"},
    {"value": "3:2", "label": "3:2"},
    {"value": "2:3", "label": "2:3"},
    {"value": "4:3", "label": "4:3"},
    {"value": "3:4", "label": "3:4"},
    {"value": "9:16", "label": "9:16"},
    {"value": "16:9", "label": "16:9"},
]


def normalize_storage_mode(value: str | None) -> str:
    mode = (value or "local").strip().lower()
    if mode in {"local", "third_party", "native"}:
        return mode
    return "local"


def normalized_model_task_timeout_seconds(value: int | None) -> int:
    """Return the persisted model timeout within the platform safety envelope.

    Admin validation and the migration enforce this range. The runtime guard only
    protects legacy/corrupt rows so an invalid value cannot create an unbounded
    worker request.
    """
    try:
        timeout_seconds = int(value or DEFAULT_MODEL_TASK_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return DEFAULT_MODEL_TASK_TIMEOUT_SECONDS
    return max(MIN_MODEL_TASK_TIMEOUT_SECONDS, min(timeout_seconds, MAX_MODEL_TASK_TIMEOUT_SECONDS))


def task_deadline_at(started_at: datetime, timeout_seconds: int | None) -> datetime:
    return started_at + timedelta(seconds=normalized_model_task_timeout_seconds(timeout_seconds))


def task_remaining_timeout_seconds(deadline_at: datetime | None, *, now: datetime | None = None) -> int:
    """Return whole seconds left in a task's fixed execution budget.

    A positive sub-second remainder is rounded down deliberately: a retry must
    never receive more budget than the task has left.
    """
    if deadline_at is None:
        return 0
    current_time = now or datetime.now(UTC)
    deadline = deadline_at if deadline_at.tzinfo else deadline_at.replace(tzinfo=UTC)
    remaining_seconds = int((deadline - current_time).total_seconds())
    return max(0, remaining_seconds)


def task_attempt_generation_config(
    config: GenerationModelConfig,
    deadline_at: datetime | None,
    *,
    now: datetime | None = None,
) -> GenerationModelConfig:
    remaining_timeout_seconds = task_remaining_timeout_seconds(deadline_at, now=now)
    if remaining_timeout_seconds <= 0:
        raise BusinessError(MODEL_TIMEOUT_MESSAGE, code=MODEL_TIMEOUT_CODE, status_code=400)
    return replace(config, timeout_seconds=remaining_timeout_seconds)


async def model_task_policy_snapshot(
    db: AsyncSession,
    model_id: int,
    site_id: int,
) -> tuple[int, bool]:
    row = (
        await db.execute(
            select(
                image_models_table.c.timeout_seconds,
                image_models_table.c.disable_retry,
            )
            .where(
                image_models_table.c.id == model_id,
                image_models_table.c.site_id == site_id,
            )
            .with_for_update()
        )
    ).first()
    if row is None:
        raise BusinessError("模型不可用", code=40404, status_code=404)
    return normalized_model_task_timeout_seconds(row.timeout_seconds), bool(row.disable_retry)


async def generation_model_config(
    db: AsyncSession,
    model_id: int,
    site_id: int,
    *,
    task_timeout_seconds: int | None = None,
    task_disable_retry: bool | None = None,
) -> GenerationModelConfig:
    result = await db.execute(
        select(
            image_models_table.c.vendor_model,
            image_models_table.c.timeout_seconds.label("model_timeout_seconds"),
            image_models_table.c.disable_retry.label("model_disable_retry"),
            image_model_providers_table.c.name.label("provider_name"),
            image_model_providers_table.c.code.label("provider_code"),
            image_model_providers_table.c.base_url,
            image_model_providers_table.c.access_mode,
            image_model_providers_table.c.auth_type,
            image_model_providers_table.c.encrypted_api_key,
            image_model_providers_table.c.is_active,
        )
        .select_from(image_models_table.join(image_model_providers_table, image_models_table.c.provider_id == image_model_providers_table.c.id))
        .where(
            image_models_table.c.id == model_id,
            image_models_table.c.site_id == site_id,
            image_model_providers_table.c.site_id == site_id,
        )
    )
    row = result.first()
    if row is None or not row.is_active:
        raise BusinessError("模型供应商不可用", code=40405, status_code=404)
    from app.services.model_cdn import for_model
    cdn = for_model(site_id, model_id)
    return GenerationModelConfig(
        cdn_key=cdn.cdn_key if cdn else "",
        native_image_base_url=cdn.result_base_url if cdn else "",
        provider_code=row.provider_code or "",
        provider_name=row.provider_name or "",
        base_url=row.base_url or "",
        access_mode=row.access_mode or "api",
        api_key=row.encrypted_api_key or "",
        auth_type=row.auth_type or "bearer",
        timeout_seconds=normalized_model_task_timeout_seconds(
            task_timeout_seconds if task_timeout_seconds is not None else row.model_timeout_seconds
        ),
        vendor_model=row.vendor_model or "",
        disable_retry=bool(
            task_disable_retry
            if task_disable_retry is not None
            else row.model_disable_retry
        ),
    )


# 超时：首次 + 再试 1 次；仍超时只提示「已超时」。其它错误不重试。
IMAGE_TIMEOUT_MAX_ATTEMPTS = 2


def image_task_max_attempts(disable_retry: bool) -> int:
    return 1 if disable_retry else IMAGE_TIMEOUT_MAX_ATTEMPTS


def is_retryable_model_error(exc: Exception) -> bool:
    """
    只有超时可自动重试（超分网关：HTTP 400 +「已超时」/ timeout）。
    其它错误一律不重试，message 直接透传给用户。
    """
    if not isinstance(exc, BusinessError):
        return False
    if exc.code == RESULT_DOWNLOAD_TIMEOUT_CODE:
        return False
    if exc.code == MODEL_TIMEOUT_CODE:
        return True
    if exc.status_code != 400:
        return False
    message = str(exc.message or "").strip()
    if message == MODEL_TIMEOUT_MESSAGE or "超时" in message:
        return True
    lower = message.lower()
    return "timeout" in lower or "timed out" in lower or "deadline exceeded" in lower


# 兼容旧测试/导入名
is_retryable_model_rate_limit = is_retryable_model_error


def image_task_failure_message(exc: Exception, max_attempts: int) -> str:
    _ = max_attempts
    if is_retryable_model_error(exc):
        # 重试 1 次后仍超时：只告诉用户超时
        return MODEL_TIMEOUT_MESSAGE
    # 非超时：直接透传 message
    return exc.message if isinstance(exc, BusinessError) else str(exc)


def image_task_retry_message(exc: Exception, attempt: int, max_attempts: int) -> str:
    if is_retryable_model_error(exc):
        return f"上游超时，已重新排队重试（{attempt}/{max_attempts}）"
    return f"模型调用失败，已重新排队重试（{attempt}/{max_attempts}）"


async def mark_image_task_status(
    db: AsyncSession,
    task_id: int,
    status: str,
    failure_message: str | None = None,
    *,
    expected_statuses: tuple[str, ...] | None = None,
) -> bool:
    condition = image_tasks_table.c.id == task_id
    if expected_statuses is not None:
        condition = and_(condition, image_tasks_table.c.status.in_(expected_statuses))
    now = datetime.now(UTC)
    values = {"status": status, "failure_message": failure_message, "finished_at": None}
    if status == "queued":
        values["worker_started_at"] = func.coalesce(image_tasks_table.c.worker_started_at, now)
        values["worker_heartbeat_at"] = now
    elif status == "running":
        timeout_seconds = await db.scalar(
            select(image_tasks_table.c.timeout_seconds).where(image_tasks_table.c.id == task_id)
        )
        values["worker_started_at"] = func.coalesce(image_tasks_table.c.worker_started_at, now)
        values["worker_heartbeat_at"] = now
        values["deadline_at"] = func.coalesce(
            image_tasks_table.c.deadline_at,
            task_deadline_at(now, timeout_seconds),
        )
    result = await db.execute(
        update(image_tasks_table)
        .where(condition)
        .values(**values)
        .returning(image_tasks_table.c.id)
    )
    await db.commit()
    return result.first() is not None


async def mark_image_task_worker_heartbeat(
    db: AsyncSession,
    task_id: int,
    *,
    expected_statuses: tuple[str, ...] = ("queued", "running"),
) -> bool:
    now = datetime.now(UTC)
    result = await db.execute(
        update(image_tasks_table)
        .where(
            image_tasks_table.c.id == task_id,
            image_tasks_table.c.status.in_(expected_statuses),
        )
        .values(
            worker_started_at=func.coalesce(image_tasks_table.c.worker_started_at, now),
            worker_heartbeat_at=now,
        )
        .returning(image_tasks_table.c.id)
    )
    await db.commit()
    return result.first() is not None


async def mark_image_task_provider_job(
    db: AsyncSession,
    task_id: int,
    *,
    provider_request_id: str,
    provider_request_snapshot: dict | None = None,
) -> bool:
    """Persist upstream job id as soon as create returns, so restarts can resume-poll."""
    job_id = str(provider_request_id or "").strip()
    if not job_id:
        return False
    values = {
        "provider_request_id": job_id,
        "worker_heartbeat_at": datetime.now(UTC),
    }
    if provider_request_snapshot is not None:
        values["provider_request_snapshot"] = json.dumps(provider_request_snapshot, ensure_ascii=False)
    result = await db.execute(
        update(image_tasks_table)
        .where(
            image_tasks_table.c.id == task_id,
            image_tasks_table.c.status.in_(("queued", "running")),
        )
        .values(**values)
        .returning(image_tasks_table.c.id)
    )
    await db.commit()
    return result.first() is not None


async def finish_image_task_failed(
    db: AsyncSession,
    *,
    task_id: int,
    user_id: int,
    task_no: str,
    credit_cost: Decimal,
    failure_message: str,
) -> bool:
    await refund_image_task_credits(db, user_id, task_no, credit_cost)
    result = await db.execute(
        update(image_tasks_table)
        .where(
            image_tasks_table.c.id == task_id,
            image_tasks_table.c.status.in_(ACTIVE_IMAGE_TASK_STATUSES),
        )
        .values(status="failed", failure_message=failure_message[:1000], finished_at=datetime.now(UTC))
        .returning(image_tasks_table.c.id)
    )
    await db.commit()
    return result.first() is not None


async def store_generated_image_collection(
    db: AsyncSession, *, generated: GeneratedImage, user_id: int, site_id: int,
    qiniu_storage_enabled: bool, storage_mode: str,
) -> tuple[ImageAsset, list[dict]]:
    assets = []
    for image in (generated, *getattr(generated, "additional_images", ())):
        stored = await run_generated_image_storage_in_executor(
            user_id=user_id, content=image.content, mime_type=image.mime_type,
            qiniu_storage_enabled=qiniu_storage_enabled, storage_mode=storage_mode,
            source_url=getattr(image, "source_url", None), hot_url=getattr(image, "hot_url", None),
        )
        assets.append(await create_generated_image_asset(
            db=db, user_id=user_id, site_id=site_id, stored_image=stored,
        ))
        # refresh() opens a read transaction; return its connection before the
        # next potentially slow CDN upload. Sessions retain loaded attributes.
        await db.commit()
    manifest = [{"url": asset.url, "r2_url": asset.r2_url,
                 "r2_expires_at": asset.r2_expires_at.isoformat() if asset.r2_expires_at else None}
                for asset in assets]
    return assets[0], manifest


async def finish_image_task_succeeded(
    db: AsyncSession,
    task_id: int,
    output_image_url: str,
    *,
    output_image_r2_url: str | None = None,
    output_image_r2_expires_at: datetime | None = None,
    output_image_assets: list[dict] | None = None,
    provider_request_id: str = "",
    provider_request_snapshot: dict | None = None,
    provider_response_summary: dict | None = None,
    provider_http_status: int | None = None,
) -> bool:
    result = await db.execute(
        update(image_tasks_table)
        .where(image_tasks_table.c.id == task_id, image_tasks_table.c.status == "running")
        .values(
            status="succeeded",
            output_image_url=output_image_url,
            output_image_assets=output_image_assets,
            output_image_r2_url=output_image_r2_url or None,
            output_image_r2_expires_at=output_image_r2_expires_at,
            failure_message=None,
            finished_at=datetime.now(UTC),
            provider_request_id=provider_request_id or None,
            provider_request_snapshot=json.dumps(provider_request_snapshot, ensure_ascii=False) if provider_request_snapshot else None,
            provider_response_summary=json.dumps(provider_response_summary, ensure_ascii=False) if provider_response_summary else None,
            provider_http_status=provider_http_status,
        )
        .returning(image_tasks_table.c.id)
    )
    await db.commit()
    return result.first() is not None


def stale_running_cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(seconds=max(1, settings.image_task_running_stale_seconds))


def stale_worker_heartbeat_cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(seconds=max(1, settings.image_task_worker_heartbeat_stale_seconds))


def live_worker_heartbeat_condition(now: datetime | None = None):
    current_time = now or datetime.now(UTC)
    heartbeat_cutoff = stale_worker_heartbeat_cutoff(current_time)
    return or_(
        image_tasks_table.c.worker_heartbeat_at >= heartbeat_cutoff,
        and_(
            image_tasks_table.c.worker_heartbeat_at.is_(None),
            image_tasks_table.c.created_at >= heartbeat_cutoff,
        ),
    )


def active_image_task_condition(now: datetime | None = None):
    current_time = now or datetime.now(UTC)
    within_task_deadline = or_(
        image_tasks_table.c.provider_http_status.is_not(None),
        image_tasks_table.c.deadline_at.is_(None),
        image_tasks_table.c.deadline_at > current_time,
    )
    return or_(
        image_tasks_table.c.status == "pending",
        # Durable queued work has no worker lease until the dispatcher claims
        # it. Queue age must not expire work or bypass account capacity limits.
        image_tasks_table.c.status == "queued",
        and_(
            image_tasks_table.c.status == "running",
            within_task_deadline,
            or_(
                image_tasks_table.c.worker_heartbeat_at >= stale_worker_heartbeat_cutoff(current_time),
                and_(
                    image_tasks_table.c.worker_heartbeat_at.is_(None),
                    image_tasks_table.c.created_at >= stale_running_cutoff(current_time),
                ),
            ),
        ),
    )


async def _try_resume_stale_video_task(db: AsyncSession, row) -> bool:
    """Best-effort resume of a running video task that already has provider_request_id."""
    task_id = int(row["id"])
    user_id = int(row["user_id"])
    site_id = int(row.get("site_id") or 0)
    model_id = int(row.get("model_id") or 0)
    job_id = str(row.get("provider_request_id") or "").strip()
    if not job_id or not model_id:
        return False

    remaining_timeout_seconds = task_remaining_timeout_seconds(row.get("deadline_at"))
    if remaining_timeout_seconds <= 0:
        return False

    snapshot_raw = row.get("provider_request_snapshot")
    snapshot: dict = {}
    if isinstance(snapshot_raw, dict):
        snapshot = snapshot_raw
    elif isinstance(snapshot_raw, str) and snapshot_raw.strip():
        try:
            loaded = json.loads(snapshot_raw)
            if isinstance(loaded, dict):
                snapshot = loaded
        except json.JSONDecodeError:
            snapshot = {}
    create_endpoint = str(snapshot.get("endpoint") or "")

    # Keep heartbeat alive while we resume-poll so concurrent reapers skip it.
    await mark_image_task_worker_heartbeat(db, task_id, expected_statuses=("running",))

    model_row = (
        await db.execute(
            select(
                image_models_table.c.id,
                image_models_table.c.vendor_model,
                image_models_table.c.storage_mode,
                image_models_table.c.timeout_seconds.label("model_timeout_seconds"),
                image_model_providers_table.c.code,
                image_model_providers_table.c.name,
                image_model_providers_table.c.base_url,
                image_model_providers_table.c.access_mode,
                image_model_providers_table.c.auth_type,
                image_model_providers_table.c.encrypted_api_key,
            )
            .select_from(
                image_models_table.join(
                    image_model_providers_table,
                    image_model_providers_table.c.id == image_models_table.c.provider_id,
                )
            )
            .where(image_models_table.c.id == model_id)
        )
    ).mappings().first()
    if not model_row:
        return False

    # encrypted_api_key is used as the live key elsewhere (see generation_model_config).
    config = GenerationModelConfig(
        provider_code=str(model_row.get("code") or ""),
        provider_name=str(model_row.get("name") or ""),
        base_url=str(model_row.get("base_url") or ""),
        access_mode=str(model_row.get("access_mode") or "api"),
        api_key=str(model_row.get("encrypted_api_key") or ""),
        auth_type=str(model_row.get("auth_type") or "bearer"),
        timeout_seconds=normalized_model_task_timeout_seconds(
            row.get("timeout_seconds") if row.get("timeout_seconds") is not None else model_row.get("model_timeout_seconds")
        ),
        vendor_model=str(model_row.get("vendor_model") or ""),
    )
    storage_mode = str(model_row.get("storage_mode") or "native")

    loop = asyncio.get_running_loop()
    generated = await loop.run_in_executor(
        image_generation_executor,
        lambda: resume_video_job(
            config,
            job_id,
            create_endpoint=create_endpoint,
            timeout=remaining_timeout_seconds,
        ),
    )
    if task_remaining_timeout_seconds(row.get("deadline_at")) <= 0:
        return False

    qiniu_storage_enabled = await get_qiniu_storage_enabled(db, site_id) if site_id else None
    stored_image = await run_generated_image_storage_in_executor(
        user_id=user_id,
        content=generated.content,
        mime_type=generated.mime_type,
        qiniu_storage_enabled=qiniu_storage_enabled,
        storage_mode=storage_mode,
        source_url=getattr(generated, "source_url", None),
        hot_url=getattr(generated, "hot_url", None),
    )
    if task_remaining_timeout_seconds(row.get("deadline_at")) <= 0:
        return False
    asset = await create_generated_image_asset(db=db, user_id=user_id, site_id=site_id or user_id, stored_image=stored_image)
    finished = await finish_image_task_succeeded(
        db,
        task_id,
        asset.url,
        output_image_r2_url=asset.r2_url,
        output_image_r2_expires_at=asset.r2_expires_at,
        provider_request_id=generated.provider_request_id or job_id,
        provider_request_snapshot=generated.provider_request_snapshot or snapshot or None,
        provider_response_summary=generated.provider_response_summary,
        provider_http_status=generated.provider_http_status,
    )
    return bool(finished)


async def reap_stale_image_tasks(db: AsyncSession, *, now: datetime | None = None, batch_size: int | None = None) -> int:
    current_time = now or datetime.now(UTC)
    limit = max(1, int(batch_size or settings.image_task_reaper_batch_size))
    result = await db.execute(
        select(
            image_tasks_table.c.id,
            image_tasks_table.c.batch_id,
            image_tasks_table.c.task_no,
            image_tasks_table.c.user_id,
            image_tasks_table.c.credit_cost,
            image_tasks_table.c.status,
            image_tasks_table.c.provider_request_id,
            image_tasks_table.c.provider_request_snapshot,
            image_tasks_table.c.work_type,
            image_tasks_table.c.model_id,
            image_tasks_table.c.site_id,
            image_tasks_table.c.timeout_seconds,
            image_tasks_table.c.deadline_at,
            image_tasks_table.c.provider_http_status,
        )
        .where(
            image_tasks_table.c.output_image_url.is_(None),
            or_(
                and_(
                    image_tasks_table.c.status == "running",
                    or_(
                        and_(
                            image_tasks_table.c.provider_http_status.is_(None),
                            image_tasks_table.c.deadline_at.is_not(None),
                            image_tasks_table.c.deadline_at <= current_time,
                        ),
                        image_tasks_table.c.worker_heartbeat_at < stale_worker_heartbeat_cutoff(current_time),
                        and_(
                            image_tasks_table.c.worker_heartbeat_at.is_(None),
                            image_tasks_table.c.created_at < stale_running_cutoff(current_time),
                        ),
                    ),
                ),
            ),
        )
        .order_by(image_tasks_table.c.created_at.asc(), image_tasks_table.c.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = result.mappings().all()
    reaped_count = 0
    for row in rows:
        provider_request_id = str(row.get("provider_request_id") or "").strip()
        work_type = str(row.get("work_type") or "")
        deadline_expired = (
            str(row.get("status") or "") == "running"
            and row.get("provider_http_status") is None
            and row.get("deadline_at") is not None
            and task_remaining_timeout_seconds(row.get("deadline_at"), now=current_time) <= 0
        )
        # If we already have an upstream job id, try resume-poll once before failing.
        if (
            not deadline_expired
            and provider_request_id
            and is_video_work_type(work_type)
            and str(row.get("status") or "") == "running"
        ):
            try:
                resumed = await _try_resume_stale_video_task(db, row)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "image_task_reaper resume_failed task_id=%s provider_request_id=%s",
                    row["id"],
                    provider_request_id,
                )
                resumed = False
            if resumed:
                logger.warning(
                    "image_task_reaper resumed_success task_id=%s task_no=%s provider_request_id=%s",
                    row["id"],
                    row["task_no"],
                    provider_request_id,
                )
                continue
        reaped = await finish_image_task_failed(
            db,
            task_id=int(row["id"]),
            user_id=int(row["user_id"]),
            task_no=str(row["task_no"]),
            credit_cost=Decimal(str(row["credit_cost"] or 0)),
            failure_message=MODEL_TASK_TIMEOUT_FAILURE_MESSAGE if deadline_expired else STALE_IMAGE_TASK_FAILURE_MESSAGE,
        )
        if reaped:
            reaped_count += 1
            logger.warning(
                "image_task_reaper reaped task_id=%s task_no=%s old_status=%s provider_request_id=%s",
                row["id"],
                row["task_no"],
                row["status"],
                provider_request_id or "-",
            )
    return reaped_count


async def image_task_reaper_loop() -> None:
    interval = max(5, int(settings.image_task_reaper_interval_seconds))
    while True:
        try:
            async with AsyncSessionLocal() as db:
                reaped_count = await reap_stale_image_tasks(db)
                if reaped_count:
                    logger.warning("image_task_reaper completed reaped_count=%s", reaped_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("image_task_reaper failed")
        await asyncio.sleep(interval)


async def image_task_worker_heartbeat_loop(task_id: int, expected_statuses: tuple[str, ...]) -> None:
    interval = max(5, int(settings.image_task_worker_heartbeat_interval_seconds))
    while True:
        async with AsyncSessionLocal() as db:
            alive = await mark_image_task_worker_heartbeat(db, task_id, expected_statuses=expected_statuses)
            if not alive:
                return
        await asyncio.sleep(interval)


def wake_image_task_dispatcher() -> None:
    image_task_dispatcher_event.set()


async def model_concurrency_limit(db: AsyncSession, model_id: int) -> int:
    value = await db.scalar(select(image_models_table.c.concurrency_limit).where(image_models_table.c.id == model_id))
    return max(0, int(value or 0))


async def user_image_concurrency_limit(db: AsyncSession, user_id: int) -> int:
    value = await db.scalar(select(User.image_concurrency_limit).where(User.id == user_id))
    return max(1, int(value or 1))


async def ensure_user_image_task_capacity(db: AsyncSession, user_id: int, requested_count: int) -> None:
    if requested_count <= 0:
        return
    from app.services.image_batch_uploads import reserved_upload_count_query
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": f"image-task-capacity:{user_id}"})
    limit = max(1, int(settings.image_task_queue_limit_per_user))
    # Count reservations and created tasks in one PostgreSQL snapshot. A
    # worker can atomically replace a reservation with tasks between polls.
    task_count_query = select(func.count()).select_from(image_tasks_table).where(
        image_tasks_table.c.user_id == user_id, active_image_task_condition(),
    ).scalar_subquery()
    active_count = int(
        await db.scalar(select(task_count_query + reserved_upload_count_query(user_id)))
        or 0
    )
    if active_count + requested_count > limit:
        raise BusinessError(
            f"当前账号最多保留 {limit} 个图片任务，已有 {active_count} 个执行或排队，请完成后再提交。",
            code=42911,
            status_code=429,
        )


async def wait_for_model_execution_turn(db: AsyncSession, task_id: int, user_id: int, model_id: int) -> bool:
    heartbeat_interval = max(5, int(settings.image_task_worker_heartbeat_interval_seconds))
    last_heartbeat_at = 0.0
    while True:
        if perf_counter() - last_heartbeat_at >= heartbeat_interval:
            heartbeat_alive = await mark_image_task_worker_heartbeat(db, task_id, expected_statuses=("queued",))
            if not heartbeat_alive:
                return False
            last_heartbeat_at = perf_counter()
        async with model_queue_lock:
            model_limit = await model_concurrency_limit(db, model_id)
            user_limit = await user_image_concurrency_limit(db, user_id)

            task_row = (
                await db.execute(
                    select(image_tasks_table.c.id, image_tasks_table.c.created_at, image_tasks_table.c.status)
                    .where(image_tasks_table.c.id == task_id)
                )
            ).first()
            if task_row is None or task_row.status != "queued":
                return False

            model_running_count = 0
            if model_limit > 0:
                model_running_count = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(image_tasks_table)
                        .where(
                            image_tasks_table.c.model_id == model_id,
                            image_tasks_table.c.status == "running",
                            active_image_task_condition(),
                        )
                    )
                    or 0
                )
            user_running_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(image_tasks_table)
                    .where(
                        image_tasks_table.c.user_id == user_id,
                        image_tasks_table.c.status == "running",
                        active_image_task_condition(),
                    )
                )
                or 0
            )
            older_user_model_queued_count = await db.scalar(
                select(func.count())
                .select_from(image_tasks_table)
                .where(
                    image_tasks_table.c.model_id == model_id,
                    image_tasks_table.c.user_id == user_id,
                    image_tasks_table.c.status == "queued",
                    or_(
                        image_tasks_table.c.created_at < task_row.created_at,
                        and_(image_tasks_table.c.created_at == task_row.created_at, image_tasks_table.c.id < task_row.id),
                    ),
                )
            )
            if (
                (model_limit <= 0 or model_running_count < model_limit)
                and user_running_count < user_limit
                and int(older_user_model_queued_count or 0) == 0
            ):
                return await mark_image_task_status(
                    db,
                    task_id,
                    "running",
                    None,
                    expected_statuses=("queued",),
                )

        await asyncio.sleep(2)


async def execute_image_task(
    db: AsyncSession,
    task_id: int,
    site_id: int,
    user_id: int,
    model_id: int,
    prompt: str,
    credit_cost: Decimal,
    task_no: str,
    input_image_url: str | None = None,
    input_image_urls: list[str] | None = None,
    resolution: str = "",
    aspect_ratio: str = "",
    quality: str = DEFAULT_IMAGE_QUALITY,
    size: str | None = None,
    output_format: str | None = None,
) -> tuple[str, str | None]:
    retry_delay = max(1, settings.image_generation_rate_limit_retry_delay_seconds)
    task_started_at = perf_counter()
    try:
        config = await generation_model_config(db, model_id, site_id)
        max_attempts = image_task_max_attempts(config.disable_retry)
        model_meta = (
            await db.execute(
                select(
                    image_models_table.c.work_type,
                    image_models_table.c.capability_type,
                    image_models_table.c.storage_mode,
                ).where(
                    image_models_table.c.id == model_id,
                    image_models_table.c.site_id == site_id,
                )
            )
        ).first()
        media_kind = (
            "video"
            if model_meta is not None
            and (
                is_video_work_type(model_meta.work_type)
                or str(model_meta.capability_type or "").strip() == "video"
            )
            else "image"
        )
        storage_mode = normalize_storage_mode(getattr(model_meta, "storage_mode", None) if model_meta else None)
    except Exception as exc:
        await db.rollback()
        failure_message = exc.message if isinstance(exc, BusinessError) else str(exc)
        await finish_image_task_failed(
            db,
            task_id=task_id,
            user_id=user_id,
            task_no=task_no,
            credit_cost=credit_cost,
            failure_message=failure_message,
        )
        return "failed", None

    for attempt in range(1, max_attempts + 1):
        attempt_started_at = perf_counter()
        queued = await mark_image_task_status(
            db,
            task_id,
            "queued",
            None,
            expected_statuses=("queued", "running"),
        )
        if not queued:
            logger.warning(
                "image_task_timing stage=skip_inactive task_no=%s task_id=%s attempt=%s",
                task_no,
                task_id,
                attempt,
            )
            return "failed", None
        try:
            wait_started_at = perf_counter()
            acquired_turn = await wait_for_model_execution_turn(db, task_id, user_id, model_id)
            if not acquired_turn:
                logger.warning(
                    "image_task_timing stage=turn_not_acquired task_no=%s task_id=%s attempt=%s",
                    task_no,
                    task_id,
                    attempt,
                )
                return "failed", None
            logger.warning(
                "image_task_timing stage=queue_wait task_no=%s task_id=%s attempt=%s elapsed=%.3fs",
                task_no,
                task_id,
                attempt,
                perf_counter() - wait_started_at,
            )
            generation_started_at = perf_counter()
            generation_inputs = input_image_urls if input_image_urls is not None else ([input_image_url] if input_image_url else None)
            heartbeat_task = asyncio.create_task(image_task_worker_heartbeat_loop(task_id, ("running",)))
            try:
                generated, timing = await run_image_generation_in_executor(
                    config,
                    prompt,
                    generation_inputs,
                    resolution,
                    aspect_ratio,
                    quality,
                    **image_output_options({"size": size, "output_format": output_format}),
                    task_no=task_no,
                    task_id=task_id,
                    user_id=user_id,
                    attempt=attempt,
                    media_kind=media_kind,
                )
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            logger.warning(
                "image_task_timing stage=upstream_generate task_no=%s task_id=%s attempt=%s elapsed=%.3fs "
                "slot_wait=%.3fs executor_wait=%.3fs generate=%.3fs bytes=%s mime_type=%s media_kind=%s storage_mode=%s",
                task_no,
                task_id,
                attempt,
                perf_counter() - generation_started_at,
                float(timing.get("slot_wait_secs") or 0),
                float(timing.get("executor_wait_secs") or 0),
                float(timing.get("generate_secs") or 0),
                len(generated.content),
                generated.mime_type,
                media_kind,
                storage_mode,
            )
            save_started_at = perf_counter()
            qiniu_storage_enabled = await get_qiniu_storage_enabled(db, site_id)
            asset, output_assets = await store_generated_image_collection(
                db, generated=generated, user_id=user_id, site_id=site_id,
                qiniu_storage_enabled=qiniu_storage_enabled, storage_mode=storage_mode,
            )
            logger.warning(
                "image_task_timing stage=save_generated_image task_no=%s task_id=%s attempt=%s elapsed=%.3fs url=%s",
                task_no,
                task_id,
                attempt,
                perf_counter() - save_started_at,
                asset.url,
            )
            db_update_started_at = perf_counter()
            finished = await finish_image_task_succeeded(
                db,
                task_id,
                asset.url,
                output_image_r2_url=asset.r2_url,
                output_image_r2_expires_at=asset.r2_expires_at,
                output_image_assets=output_assets,
                provider_request_id=generated.provider_request_id,
                provider_request_snapshot=generated.provider_request_snapshot,
                provider_response_summary=generated.provider_response_summary,
                provider_http_status=generated.provider_http_status,
            )
            if not finished:
                logger.warning(
                    "image_task_timing stage=finish_success_skipped task_no=%s task_id=%s attempt=%s asset_url=%s",
                    task_no,
                    task_id,
                    attempt,
                    asset.url,
                )
                return "failed", None
            logger.warning(
                "image_task_timing stage=finish_success task_no=%s task_id=%s attempt=%s db_update_elapsed=%.3fs attempt_elapsed=%.3fs total_elapsed=%.3fs",
                task_no,
                task_id,
                attempt,
                perf_counter() - db_update_started_at,
                perf_counter() - attempt_started_at,
                perf_counter() - task_started_at,
            )
            return "succeeded", asset.url
        except Exception as exc:
            logger.warning(
                "image_task_timing stage=attempt_failed task_no=%s task_id=%s attempt=%s elapsed=%.3fs error_type=%s error=%s",
                task_no,
                task_id,
                attempt,
                perf_counter() - attempt_started_at,
                type(exc).__name__,
                str(exc)[:300],
            )
            await db.rollback()
            if is_retryable_model_error(exc) and attempt < max_attempts:
                await mark_image_task_status(
                    db,
                    task_id,
                    "queued",
                    image_task_retry_message(exc, attempt, max_attempts),
                )
                await asyncio.sleep(retry_delay * attempt)
                continue

            failure_message = image_task_failure_message(exc, max_attempts)
            await finish_image_task_failed(
                db,
                task_id=task_id,
                user_id=user_id,
                task_no=task_no,
                credit_cost=credit_cost,
                failure_message=failure_message,
            )
            return "failed", None

    return "failed", None


async def execute_image_task_session(
    task_id: int,
    site_id: int,
    user_id: int,
    model_id: int,
    prompt: str,
    credit_cost: Decimal,
    task_no: str,
    input_image_url: str | None = None,
    input_image_urls: list[str] | None = None,
    resolution: str = "",
    aspect_ratio: str = "",
    quality: str = DEFAULT_IMAGE_QUALITY,
    size: str | None = None,
    output_format: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        await execute_image_task(
            db,
            task_id=task_id,
            site_id=site_id,
            user_id=user_id,
            model_id=model_id,
            prompt=prompt,
            credit_cost=credit_cost,
            task_no=task_no,
            input_image_url=input_image_url,
            input_image_urls=input_image_urls,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            quality=quality,
            size=size, output_format=output_format,
        )


def parse_input_image_urls(value: str | None) -> list[str] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    urls = [str(item) for item in parsed if item]
    return urls or None


async def execute_claimed_image_task(payload: dict) -> None:
    task_id = int(payload["task_id"])
    task_no = str(payload["task_no"])
    site_id = int(payload["site_id"])
    user_id = int(payload["user_id"])
    model_id = int(payload["model_id"])
    prompt = str(payload.get("prompt") or "")
    credit_cost = Decimal(str(payload.get("credit_cost") or 0))
    input_image_url = payload.get("input_image_url")
    input_image_urls = payload.get("input_image_urls")
    resolution = str(payload.get("resolution") or "")
    aspect_ratio = str(payload.get("aspect_ratio") or "")
    quality = normalize_image_quality(payload.get("quality"))
    output_options = image_output_options(payload)
    task_timeout_seconds = normalized_model_task_timeout_seconds(payload.get("timeout_seconds"))
    task_disable_retry = bool(payload.get("disable_retry"))
    deadline_at = payload.get("deadline_at")
    max_attempts = image_task_max_attempts(task_disable_retry)
    retry_delay = max(1, settings.image_generation_rate_limit_retry_delay_seconds)
    task_started_at = perf_counter()

    try:
        async with AsyncSessionLocal() as db:
            task_row = (
                await db.execute(
                    select(
                        image_tasks_table.c.timeout_seconds,
                        image_tasks_table.c.disable_retry,
                        image_tasks_table.c.deadline_at,
                    ).where(
                        image_tasks_table.c.id == task_id,
                        image_tasks_table.c.status == "running",
                    )
                )
            ).mappings().first()
            if task_row is None:
                return
            task_timeout_seconds = normalized_model_task_timeout_seconds(task_row.get("timeout_seconds"))
            task_disable_retry = bool(task_row.get("disable_retry"))
            max_attempts = image_task_max_attempts(task_disable_retry)
            deadline_at = task_row.get("deadline_at") or deadline_at
            config = await generation_model_config(
                db,
                model_id,
                site_id,
                task_timeout_seconds=task_timeout_seconds,
                task_disable_retry=task_disable_retry,
            )
            model_meta = (
                await db.execute(
                    select(
                        image_models_table.c.work_type,
                        image_models_table.c.capability_type,
                        image_models_table.c.storage_mode,
                    ).where(
                        image_models_table.c.id == model_id,
                        image_models_table.c.site_id == site_id,
                    )
                )
            ).first()
            media_kind = (
                "video"
                if model_meta is not None
                and (
                    is_video_work_type(model_meta.work_type)
                    or str(model_meta.capability_type or "").strip() == "video"
                )
                else "image"
            )
            storage_mode = normalize_storage_mode(getattr(model_meta, "storage_mode", None) if model_meta else None)
    except Exception as exc:
        failure_message = exc.message if isinstance(exc, BusinessError) else str(exc)
        async with AsyncSessionLocal() as db:
            await finish_image_task_failed(
                db,
                task_id=task_id,
                user_id=user_id,
                task_no=task_no,
                credit_cost=credit_cost,
                failure_message=failure_message,
            )
        return

    for attempt in range(1, max_attempts + 1):
        attempt_started_at = perf_counter()
        if deadline_at is None and attempt > 1:
            async with AsyncSessionLocal() as db:
                deadline_at = await db.scalar(
                    select(image_tasks_table.c.deadline_at).where(
                        image_tasks_table.c.id == task_id,
                        image_tasks_table.c.status == "running",
                    )
                )
        try:
            attempt_config = (
                task_attempt_generation_config(config, deadline_at)
                if deadline_at is not None
                else config
            )
        except BusinessError:
            async with AsyncSessionLocal() as db:
                await finish_image_task_failed(
                    db,
                    task_id=task_id,
                    user_id=user_id,
                    task_no=task_no,
                    credit_cost=credit_cost,
                    failure_message=MODEL_TASK_TIMEOUT_FAILURE_MESSAGE,
                )
            wake_image_task_dispatcher()
            return
        heartbeat_task = asyncio.create_task(image_task_worker_heartbeat_loop(task_id, ("running",)))
        try:
            generation_started_at = perf_counter()
            generation_inputs = input_image_urls if input_image_urls is not None else ([input_image_url] if input_image_url else None)
            generated, timing = await run_image_generation_in_executor(
                attempt_config,
                prompt,
                generation_inputs,
                resolution,
                aspect_ratio,
                quality,
                **output_options,
                task_no=task_no,
                task_id=task_id,
                user_id=user_id,
                attempt=attempt,
                media_kind=media_kind,
            )
            logger.warning(
                "image_task_timing stage=upstream_generate task_no=%s task_id=%s attempt=%s elapsed=%.3fs "
                "slot_wait=%.3fs executor_wait=%.3fs generate=%.3fs bytes=%s mime_type=%s media_kind=%s storage_mode=%s",
                task_no,
                task_id,
                attempt,
                perf_counter() - generation_started_at,
                float(timing.get("slot_wait_secs") or 0),
                float(timing.get("executor_wait_secs") or 0),
                float(timing.get("generate_secs") or 0),
                len(generated.content),
                generated.mime_type,
                media_kind,
                storage_mode,
            )

            save_started_at = perf_counter()
            async with AsyncSessionLocal() as db:
                qiniu_storage_enabled = await get_qiniu_storage_enabled(db, site_id)
            async with AsyncSessionLocal() as db:
                asset, output_assets = await store_generated_image_collection(
                    db, generated=generated, user_id=user_id, site_id=site_id,
                    qiniu_storage_enabled=qiniu_storage_enabled, storage_mode=storage_mode,
                )
            async with AsyncSessionLocal() as db:
                logger.warning(
                    "image_task_timing stage=save_generated_image task_no=%s task_id=%s attempt=%s elapsed=%.3fs url=%s",
                    task_no,
                    task_id,
                    attempt,
                    perf_counter() - save_started_at,
                    asset.url,
                )
                db_update_started_at = perf_counter()
                finished = await finish_image_task_succeeded(
                    db,
                    task_id,
                    asset.url,
                    output_image_r2_url=asset.r2_url,
                    output_image_r2_expires_at=asset.r2_expires_at,
                    output_image_assets=output_assets,
                    provider_request_id=generated.provider_request_id,
                    provider_request_snapshot=generated.provider_request_snapshot,
                    provider_response_summary=generated.provider_response_summary,
                    provider_http_status=generated.provider_http_status,
                )
            if not finished:
                logger.warning(
                    "image_task_timing stage=finish_success_skipped task_no=%s task_id=%s attempt=%s asset_url=%s",
                    task_no,
                    task_id,
                    attempt,
                    asset.url,
                )
                return
            logger.warning(
                "image_task_timing stage=finish_success task_no=%s task_id=%s attempt=%s db_update_elapsed=%.3fs attempt_elapsed=%.3fs total_elapsed=%.3fs",
                task_no,
                task_id,
                attempt,
                perf_counter() - db_update_started_at,
                perf_counter() - attempt_started_at,
                perf_counter() - task_started_at,
            )
            wake_image_task_dispatcher()
            return
        except Exception as exc:
            logger.warning(
                "image_task_timing stage=attempt_failed task_no=%s task_id=%s attempt=%s elapsed=%.3fs error_type=%s error=%s",
                task_no,
                task_id,
                attempt,
                perf_counter() - attempt_started_at,
                type(exc).__name__,
                str(exc)[:300],
            )
            if is_retryable_model_error(exc) and attempt < max_attempts:
                async with AsyncSessionLocal() as db:
                    alive = await mark_image_task_status(
                        db,
                        task_id,
                        "running",
                        image_task_retry_message(exc, attempt, max_attempts),
                        expected_statuses=("running",),
                    )
                if not alive:
                    return
                await asyncio.sleep(retry_delay * attempt)
                continue

            failure_message = image_task_failure_message(exc, max_attempts)
            async with AsyncSessionLocal() as db:
                await finish_image_task_failed(
                    db,
                    task_id=task_id,
                    user_id=user_id,
                    task_no=task_no,
                    credit_cost=credit_cost,
                    failure_message=failure_message,
                )
            wake_image_task_dispatcher()
            return
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


async def queued_image_task_payloads_for_dispatch(db: AsyncSession, *, limit: int) -> list[dict]:
    # The in-process dispatcher lock protects asyncio tasks in one worker, but
    # it cannot coordinate multiple Uvicorn workers/instances. Serialize only
    # the short claim transaction so user/model limits are calculated from a
    # current snapshot before another dispatcher can claim rows.
    lock_result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
        {"lock_key": IMAGE_TASK_DISPATCHER_ADVISORY_LOCK_KEY},
    )
    if not bool(lock_result.scalar_one()):
        await db.rollback()
        return []
    current_time = datetime.now(UTC)
    # Page through lightweight rows, excluding users/models as soon as their
    # capacity is exhausted. Increasing a fixed lookahead cannot prevent a
    # large batch from hiding all eligible tasks behind it.
    candidate_limit = min(max(limit * 4, limit + 64), 4000)
    selected: list[dict] = []
    user_limits: dict[int, int] = {}
    model_limits: dict[int, int] = {}
    user_running: dict[int, int] = {}
    model_running: dict[int, int] = {}
    cursor = None
    while len(selected) < limit:
        candidate_filters = []
        saturated_users = [uid for uid, cap in user_limits.items() if user_running.get(uid, 0) >= cap]
        saturated_models = [mid for mid, cap in model_limits.items() if cap > 0 and model_running.get(mid, 0) >= cap]
        if saturated_users:
            candidate_filters.append(image_tasks_table.c.user_id.not_in(saturated_users))
        if saturated_models:
            candidate_filters.append(image_tasks_table.c.model_id.not_in(saturated_models))
        if cursor is not None:
            candidate_filters.append(or_(
                image_tasks_table.c.created_at > cursor[0],
                and_(image_tasks_table.c.created_at == cursor[0], image_tasks_table.c.id > cursor[1]),
            ))
        rows = (
            await db.execute(
                select(
                    image_tasks_table.c.id,
                    image_tasks_table.c.task_no,
                    image_tasks_table.c.site_id,
                    image_tasks_table.c.user_id,
                    image_tasks_table.c.model_id,
                    image_tasks_table.c.credit_cost,
                    image_tasks_table.c.created_at,
                    image_tasks_table.c.timeout_seconds,
                    image_tasks_table.c.disable_retry,
                )
                .where(
                    image_tasks_table.c.status == "queued",
                )
                .where(*candidate_filters)
                .order_by(image_tasks_table.c.created_at.asc(), image_tasks_table.c.id.asc())
                .limit(candidate_limit)
                .with_for_update(skip_locked=True)
            )
        ).mappings().all()
        if not rows:
            break
        cursor = (rows[-1]["created_at"], rows[-1]["id"])
        user_ids = sorted({int(row["user_id"]) for row in rows} - user_limits.keys())
        model_ids = sorted({int(row["model_id"]) for row in rows} - model_limits.keys())
        user_limits.update({
            int(row.id): max(1, int(row.image_concurrency_limit or 1))
            for row in await db.execute(select(User.id, User.image_concurrency_limit).where(User.id.in_(user_ids)))
        })
        model_limits.update({
            int(row.id): max(0, int(row.concurrency_limit or 0))
            for row in await db.execute(select(image_models_table.c.id, image_models_table.c.concurrency_limit).where(image_models_table.c.id.in_(model_ids)))
        })
        user_running.update({
            int(row.user_id): int(row.count)
            for row in (
                await db.execute(
                    select(image_tasks_table.c.user_id, func.count().label("count"))
                    .where(
                        image_tasks_table.c.user_id.in_(user_ids),
                        image_tasks_table.c.status == "running",
                        active_image_task_condition(current_time),
                    )
                    .group_by(image_tasks_table.c.user_id)
                )
            )
        })
        model_running.update({
            int(row.model_id): int(row.count)
            for row in (
                await db.execute(
                    select(image_tasks_table.c.model_id, func.count().label("count"))
                    .where(
                        image_tasks_table.c.model_id.in_(model_ids),
                        image_tasks_table.c.status == "running",
                        active_image_task_condition(current_time),
                    )
                    .group_by(image_tasks_table.c.model_id)
                )
            )
        })
        for row in rows:
            # Include claims from this transaction in both concurrency budgets.
            if len(selected) >= limit:
                break
            user_id = int(row["user_id"])
            model_id = int(row["model_id"])
            user_limit = user_limits.get(user_id, 1)
            model_limit = model_limits.get(model_id, 0)
            if user_running.get(user_id, 0) >= user_limit:
                continue
            if model_limit > 0 and model_running.get(model_id, 0) >= model_limit:
                continue
            timeout_seconds = normalized_model_task_timeout_seconds(row.get("timeout_seconds"))
            selected.append(
                {
                    "task_id": int(row["id"]),
                    "task_no": row["task_no"],
                    "site_id": int(row["site_id"]),
                    "user_id": user_id,
                    "model_id": model_id,
                    "credit_cost": Decimal(str(row["credit_cost"] or 0)),
                    "timeout_seconds": timeout_seconds,
                    "disable_retry": bool(row["disable_retry"]),
                }
            )
            user_running[user_id] = user_running.get(user_id, 0) + 1
            model_running[model_id] = model_running.get(model_id, 0) + 1

    if not selected:
        await db.rollback()
        return []
    now = datetime.now(UTC)
    selected_ids = [int(task_payload["task_id"]) for task_payload in selected]
    result = await db.execute(
        update(image_tasks_table)
        .where(
            image_tasks_table.c.id.in_(selected_ids),
            image_tasks_table.c.status == "queued",
        )
        .values(
            status="running",
            failure_message=None,
            worker_started_at=now,
            worker_heartbeat_at=now,
            # 模型 deadline 在完成输入准备、真正发起上游请求前设置。
            deadline_at=None,
            provider_http_status=None,
        )
        .returning(image_tasks_table.c.id)
    )
    claimed_ids = {int(task_id) for task_id in result.scalars().all()}
    if claimed_ids:
        # Prompts and input URL lists can be large for imported batches. Fetch
        # those payload fields only after the lightweight candidate scan has
        # selected tasks that actually fit the user/model concurrency limits.
        payload_rows = await db.execute(
            select(
                image_tasks_table.c.id,
                image_tasks_table.c.prompt,
                image_tasks_table.c.input_image_url,
                image_tasks_table.c.input_image_urls,
                image_tasks_table.c.resolution,
                image_tasks_table.c.aspect_ratio,
                image_tasks_table.c.quality,
                image_tasks_table.c.size,
                image_tasks_table.c.output_format,
            ).where(image_tasks_table.c.id.in_(claimed_ids))
        )
        payload_by_id = {int(row.id): row for row in payload_rows}
        selected = [
            {
                **payload,
                "prompt": payload_by_id[task_id].prompt or "",
                "input_image_url": payload_by_id[task_id].input_image_url,
                "input_image_urls": parse_input_image_urls(payload_by_id[task_id].input_image_urls),
                "resolution": payload_by_id[task_id].resolution or "",
                "aspect_ratio": payload_by_id[task_id].aspect_ratio or "",
                "quality": normalize_image_quality(payload_by_id[task_id].quality),
                **image_output_options({"size": payload_by_id[task_id].size, "output_format": payload_by_id[task_id].output_format}),
            }
            for payload in selected
            if (task_id := int(payload["task_id"])) in claimed_ids and task_id in payload_by_id
        ]
    await db.commit()
    return [payload for payload in selected if int(payload["task_id"]) in claimed_ids]


async def dispatch_image_tasks_once(*, batch_size: int | None = None) -> int:
    """从队列 claim 并拉起执行；受 max_inflight 限流，避免一次塞爆线程池。"""
    async with image_task_dispatcher_tasks_lock:
        max_inflight = max(1, int(settings.image_task_dispatcher_max_inflight))
        batch_limit = max(1, int(batch_size or settings.image_task_dispatcher_batch_size))
        current_inflight = len(image_task_dispatcher_tasks)
        free_slots = max_inflight - current_inflight
        if free_slots <= 0:
            logger.warning(
                "image_task_dispatcher skip_full inflight=%s max_inflight=%s",
                current_inflight,
                max_inflight,
            )
            return 0
        limit = min(batch_limit, free_slots)

        # DB claim 必须与内存槽位检查保持在同一进程锁内。否则另一个
        # dispatcher 可能在这里插入任务，导致已被标记 running 的任务没有
        # 对应 asyncio task，只能等 reaper 超时。
        async with AsyncSessionLocal() as db:
            payloads = await queued_image_task_payloads_for_dispatch(db, limit=limit)
        if not payloads:
            return 0

        for payload in payloads:
            task = asyncio.create_task(execute_claimed_image_task(payload))
            image_task_dispatcher_tasks.add(task)
            task.add_done_callback(image_task_dispatcher_tasks.discard)
    logger.warning(
        "image_task_dispatcher dispatched_count=%s inflight_after=%s max_inflight=%s batch_limit=%s",
        len(payloads),
        len(image_task_dispatcher_tasks),
        max_inflight,
        batch_limit,
    )
    return len(payloads)


async def image_task_dispatcher_loop() -> None:
    interval = max(1, int(settings.image_task_dispatcher_interval_seconds))
    while True:
        try:
            while True:
                dispatched_count = await dispatch_image_tasks_once()
                if dispatched_count <= 0:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("image_task_dispatcher failed")

        try:
            await asyncio.wait_for(image_task_dispatcher_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        image_task_dispatcher_event.clear()


async def execute_image_task_batch(background_payloads: list[dict]) -> None:
    """批量提交后触发调度；单次仍受 dispatcher max_inflight / batch_size 限制。"""
    # 不一次按 len(payloads) 全 claim：高峰上百任务会把线程池打满，排队被算进生图耗时
    await dispatch_image_tasks_once()
    wake_image_task_dispatcher()


@router.get("/models", response_model=StandardResponse[list])
async def models(
    work_type: str = "image_edit",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    work_types = requested_work_types(work_type)
    result = await db.execute(
        select(
            image_models_table.c.id,
            image_models_table.c.name,
            image_models_table.c.vendor_model,
            image_models_table.c.code,
            image_models_table.c.work_type,
            image_models_table.c.capability_type,
            image_models_table.c.description,
            image_models_table.c.is_recommended,
            image_models_table.c.is_stable,
            image_models_table.c.is_new,
            image_models_table.c.speed_hint,
            image_models_table.c.risk_hint,
            image_models_table.c.max_input_images,
            image_models_table.c.max_output_images,
            image_models_table.c.is_public,
            image_models_table.c.storage_mode,
            image_model_providers_table.c.code.label("provider_code"),
            image_model_providers_table.c.name.label("provider_name"),
            image_model_providers_table.c.base_url,
            image_model_providers_table.c.access_mode,
        )
        .select_from(image_models_table.outerjoin(image_model_providers_table,
            and_(image_models_table.c.provider_id == image_model_providers_table.c.id,
                 image_models_table.c.site_id == image_model_providers_table.c.site_id)))
        .where(
            image_models_table.c.site_id == current_user.site_id,
            image_models_table.c.is_active.is_(True),
            or_(image_models_table.c.is_public.is_(True), bool(getattr(current_user, "is_internal", False))),
        )
        .order_by(image_models_table.c.sort_order.asc(), image_models_table.c.id.desc())
    )
    items = []
    for model in result:
        if not model_supports_work_type(model.work_type, work_types):
            continue
        resolutions, aspect_ratios, durations = await model_options(db, model.id)
        video_model = is_video_work_type(model.work_type) or (str(model.capability_type or "").strip() == "video")
        text_model = (str(model.capability_type or "").strip() == "text") or model_supports_work_type(
            model.work_type, ["text", "text_generation"]
        )
        if video_model:
            if not resolutions or not durations:
                continue
            # Real ratios for generation; durations stay separate for billing + UI.
            video_ratios = aspect_ratios or list(DEFAULT_VIDEO_ASPECT_RATIOS)
        elif text_model:
            # Text / prompt-optimize models are priced as default/default; no image matrix required.
            resolutions = resolutions or [{"value": "default", "label": "默认"}]
            aspect_ratios = aspect_ratios or [{"value": "default", "label": "默认"}]
            video_ratios = aspect_ratios
        else:
            if not resolutions or not aspect_ratios:
                continue
            video_ratios = aspect_ratios
        items.append(
            {
                "id": model.id,
                "name": model.name,
                "code": model.code,
                "work_type": work_type,
                "capability_type": (
                    "video" if video_model else ("text" if text_model else (model.capability_type or "image"))
                ),
                "description": model.description,
                "is_recommended": model.is_recommended,
                "is_stable": model.is_stable,
                "is_new": model.is_new,
                "speed_hint": model.speed_hint,
                "risk_hint": model.risk_hint,
                "max_input_images": model.max_input_images,
                "max_output_images": model.max_output_images,
                "images_per_generation": images_per_generation(model.vendor_model),
                "supports_quality": not is_banana_images_model(model.vendor_model),
                "storage_mode": normalize_storage_mode(getattr(model, "storage_mode", None)),
                **image_output_capabilities(GenerationModelConfig(
                    provider_code=model.provider_code or "", provider_name=model.provider_name or "",
                    base_url=model.base_url or "", access_mode=model.access_mode or "api",
                    api_key="", auth_type="bearer", timeout_seconds=120, vendor_model=model.vendor_model or "",
                )),
                "supported_resolutions": resolutions,
                "supported_aspect_ratios": video_ratios if video_model else aspect_ratios,
                "supported_durations": durations if video_model else [],
            }
        )
    return ok(items)


@router.post("/models/{model_id}/quote", response_model=StandardResponse[dict])
async def quote(
    model_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    model = await db.execute(
        select(
            image_models_table.c.id,
            image_models_table.c.work_type,
            image_models_table.c.capability_type,
            image_models_table.c.is_active,
            image_models_table.c.is_public,
        ).where(
            image_models_table.c.id == model_id,
            image_models_table.c.site_id == current_user.site_id,
        )
    )
    model_row = model.first()
    if model_row is None or not model_row.is_active:
        raise BusinessError(code=40404, message="模型不可用", status_code=404)
    if not model_row.is_public and not bool(getattr(current_user, "is_internal", False)):
        raise BusinessError(code=40404, message="模型不可用", status_code=404)
    work_type = str(payload.get("work_type") or "image_edit")
    work_types = requested_work_types(work_type)
    if not model_supports_work_type(model_row.work_type, work_types):
        raise BusinessError(code=40001, message="该模型不支持当前创作类型")
    resolution = str(payload.get("resolution") or "")
    aspect_ratio = str(payload.get("aspect_ratio") or "")
    quality = normalize_image_quality(payload.get("quality"))
    output_options = image_output_options(payload)
    if output_options:
        config = await generation_model_config(db, model_id, current_user.site_id)
        validate_image_output_options(config, output_options.get("size"), output_options.get("output_format"))
    duration = str(payload.get("duration") or "").strip()
    try:
        output_count = int(payload.get("n") or payload.get("output_count") or 1)
    except (TypeError, ValueError) as exc:
        raise BusinessError("生成张数必须是整数", code=40001) from exc
    if output_count < 1:
        raise BusinessError("生成张数必须大于 0", code=40001)
    video_model = is_video_work_type(model_row.work_type) or (str(model_row.capability_type or "").strip() == "video")
    # Video pricing matrix is still resolution × duration; duration is stored in price.aspect_ratio.
    price_aspect_ratio = (duration or aspect_ratio) if video_model else aspect_ratio
    if video_model and not duration and aspect_ratio and "|" in aspect_ratio:
        _, packed_duration = unpack_video_task_aspect(aspect_ratio)
        price_aspect_ratio = packed_duration or aspect_ratio
    priced_quality = "medium" if quality == "auto" else quality
    price = await db.execute(
        select(
            image_model_prices_table.c.id,
            image_model_prices_table.c.version,
            image_model_prices_table.c.fixed_surcharge,
            image_model_prices_table.c.quality,
            image_model_prices_table.c.work_type,
            image_model_prices_table.c.credit_cost,
            image_model_prices_table.c.effective_at,
        )
        .where(
            image_model_prices_table.c.model_id == model_id,
            image_model_prices_table.c.site_id == current_user.site_id,
            image_model_prices_table.c.work_type.in_(work_types),
            image_model_prices_table.c.resolution == resolution,
            image_model_prices_table.c.aspect_ratio == price_aspect_ratio,
            image_model_prices_table.c.output_count == output_count,
            image_model_prices_table.c.quality.in_([priced_quality, "any"]),
            image_model_prices_table.c.is_active.is_(True),
        )
        .order_by(
            (image_model_prices_table.c.quality == priced_quality).desc(),
            image_model_prices_table.c.effective_at.desc(),
            image_model_prices_table.c.id.desc(),
        )
    )
    price_row = price.first()
    if price_row is None:
        raise BusinessError(code=40004, message="当前模型规格未配置价格")
    result = await customer_price(db, current_user, price_row)
    result["pricing"].update({"requested_quality": quality, "price_quality": price_row.quality})
    return ok(result)


@router.post("/image-tasks", response_model=StandardResponse[dict | list])
async def create_image_task(
    payload: dict,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict | list]:
    # A task record stores one result image. Route multi-output requests through
    # the batch creator so each output keeps independent status, retry, and billing.
    requested_work_type = str(payload.get("work_type") or "image_edit").strip()
    try:
        requested_output_count = int(payload.get("n") or payload.get("output_count") or 1)
    except (TypeError, ValueError) as exc:
        raise BusinessError("生成张数必须是整数", code=40001) from exc
    if requested_output_count < 1:
        raise BusinessError("生成张数必须大于 0", code=40001)
    if requested_output_count > 1 and requested_work_type in {"text_to_image", "image_to_image", "image_edit"}:
        return await create_batch_image_tasks(payload, background_tasks, current_user, db)

    quote_result = await quote(int(payload.get("model_id") or 0), payload, current_user, db)
    credit_cost = Decimal(str(quote_result.data["credit_cost"]))
    model_id = int(payload.get("model_id") or 0)
    model_name = str(
        await db.scalar(
            select(image_models_table.c.name).where(
                image_models_table.c.id == model_id,
                image_models_table.c.site_id == current_user.site_id,
            )
        )
        or ""
    )
    task_timeout_seconds, task_disable_retry = await model_task_policy_snapshot(
        db,
        model_id,
        current_user.site_id,
    )
    resolution = str(payload.get("resolution") or "")
    aspect_ratio = str(payload.get("aspect_ratio") or "")
    quality = normalize_image_quality(payload.get("quality"))
    output_options = image_output_options(payload)
    duration = str(payload.get("duration") or "").strip()
    work_type_value = str(payload.get("work_type") or "image_edit")
    if is_video_work_type(work_type_value) or work_type_value in {"text_to_video", "image_to_video"}:
        duration_digits = "".join(ch for ch in duration if ch.isdigit()) if duration else ""
        if duration_digits:
            duration_seconds = int(duration_digits)
            if duration_seconds < 1 or duration_seconds > 15:
                raise BusinessError(code=40001, message=f"视频时长需在 1–15 秒之间，当前为 {duration_seconds} 秒")
        aspect_ratio = pack_video_task_aspect(aspect_ratio, duration)
    max_input_images = await db.scalar(
        select(image_models_table.c.max_input_images).where(
            image_models_table.c.id == model_id,
            image_models_table.c.site_id == current_user.site_id,
        )
    )
    input_image_urls = await resolve_input_image_urls(
        db,
        site_id=current_user.site_id,
        user_id=current_user.id,
        payload=payload,
        max_input_images=max(0, int(max_input_images or 0)),
    )
    input_image_url = input_image_urls[0] if input_image_urls else None
    await ensure_user_image_task_capacity(db, current_user.id, 1)
    team_id = await get_primary_team_id(db, current_user)
    task_no = f"IMG{uuid4().hex[:16].upper()}"
    batch_id = str(payload.get("batch_id") or "").strip()[:64] or f"batch-{uuid4().hex}"
    sub2_receipt = await debit_image_task_credits(db, current_user.id, task_no, credit_cost)
    try:
        result = await db.execute(
            image_tasks_table.insert()
            .values(
                task_no=task_no,
                batch_id=batch_id,
                site_id=current_user.site_id,
                team_id=team_id,
                user_id=current_user.id,
                model_id=model_id,
                work_type=payload.get("work_type", "image_edit"),
                prompt=payload.get("prompt", ""),
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                quality=quality,
                **output_options,
                credit_cost=credit_cost,
                pricing_snapshot=quote_result.data["pricing"],
                status="queued",
                timeout_seconds=task_timeout_seconds,
                disable_retry=task_disable_retry,
                input_image_url=input_image_url,
                input_image_urls=dump_input_image_urls(input_image_urls),
            )
            .returning(image_tasks_table.c.id, image_tasks_table.c.created_at)
        )
        row = result.one()
        await db.commit()
    except Exception:
        await compensate_image_task_creation_debits(db, [sub2_receipt] if sub2_receipt is not None else [])
        raise
    background_tasks.add_task(
        execute_image_task_batch,
        [
            {
                "task_id": row.id,
                "site_id": current_user.site_id,
                "user_id": current_user.id,
                "model_id": model_id,
                "prompt": payload.get("prompt", ""),
                "credit_cost": credit_cost,
                "timeout_seconds": task_timeout_seconds,
                "disable_retry": task_disable_retry,
                "task_no": task_no,
                "batch_id": batch_id,
                "input_image_url": input_image_url,
                "input_image_urls": input_image_urls,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "quality": quality, **output_options,
            }
        ],
    )
    return ok(
        serialize_task(
            {
                "id": row.id,
                "task_no": task_no,
                "batch_id": batch_id,
                "work_type": payload.get("work_type", "image_edit"),
                "model_id": model_id,
                "model_name": model_name,
                "prompt": payload.get("prompt", ""),
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "quality": quality, **output_options,
                "credit_cost": credit_cost,
                "status": "queued",
                "failure_message": None,
                "input_image_url": input_image_url,
                "input_image_urls": dump_input_image_urls(input_image_urls),
                "output_image_url": None,
                "created_at": row.created_at,
                "finished_at": None,
            }
        )
    )


@router.post("/image-tasks/batch-upload", status_code=202, response_model=StandardResponse[dict])
async def upload_image_batch(
    manifest: UploadFile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    from app.services.image_batch_uploads import accept_manifest, parse_manifest
    try:
        raw = await manifest.read(settings.batch_upload_max_bytes + 1)
        value = parse_manifest(raw)
        return ok(await accept_manifest(db, current_user, value))
    finally:
        await manifest.close()


@router.post("/image-tasks/batch", response_model=StandardResponse[dict])
async def create_batch_image_tasks(
    payload: dict,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    work_type = str(payload.get("work_type") or "").strip()
    if work_type not in {"batch_generate", "batch_edit", "text_to_image", "image_to_image", "image_edit"}:
        raise BusinessError("当前接口不支持该批量创作类型", code=40034)

    model_id = int(payload.get("model_id") or 0)
    resolution = str(payload.get("resolution") or "")
    aspect_ratio = str(payload.get("aspect_ratio") or "")
    quality = normalize_image_quality(payload.get("quality"))
    output_options = image_output_options(payload)
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) > MAX_BATCH_PROMPT_CHARS:
        raise BusinessError("批量提示词文件过大，请拆分后再提交", code=40041)
    prompt_mode = str(payload.get("prompt_mode") or "shared").strip()
    try:
        requested_output_count = int(payload.get("n") or payload.get("output_count") or 1)
    except (TypeError, ValueError) as exc:
        raise BusinessError("生成张数必须是整数", code=40001) from exc
    if requested_output_count < 1:
        raise BusinessError("生成张数必须大于 0", code=40001)

    supplied_batch_id = str(payload.get("batch_id") or "").strip()
    batch_id = supplied_batch_id or f"batch-{uuid4().hex}"
    request_hash = None
    if prompt_mode == "grouped" or supplied_batch_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
            raise BusinessError("批次编号格式错误", code=40043)
    if prompt_mode == "grouped":
        request_hash = hashlib.sha256(json.dumps({
            "model_id": model_id, "work_type": work_type, "resolution": resolution,
            "aspect_ratio": aspect_ratio, "quality": quality, **output_options, "groups": payload.get("groups"),
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    else:
        batch_id = batch_id[:64]

    quote_result = await quote(model_id, {**payload, "output_count": 1, "n": 1}, current_user, db)
    credit_cost = Decimal(str(quote_result.data["credit_cost"]))
    task_timeout_seconds, task_disable_retry = await model_task_policy_snapshot(
        db,
        model_id,
        current_user.site_id,
    )

    task_inputs: list[dict[str, object]] = []
    if prompt_mode == "grouped":
        if work_type != "batch_edit":
            raise BusinessError("文件夹任务组仅支持批量改图", code=40043)
        max_inputs = await db.scalar(select(image_models_table.c.max_input_images).where(
            image_models_table.c.id == model_id, image_models_table.c.site_id == current_user.site_id,
        ))
        groups = validate_batch_groups(payload.get("groups"), int(max_inputs or 0))
        all_ids = {asset_id for group in groups for asset_id in group["input_image_ids"]}
        asset_rows = (await db.execute(select(image_assets_table.c.id, image_assets_table.c.url).where(
            image_assets_table.c.user_id == current_user.id,
            image_assets_table.c.site_id == current_user.site_id,
            image_assets_table.c.id.in_(all_ids),
        ))).all()
        asset_urls = {row.id: row.url for row in asset_rows}
        if all_ids - asset_urls.keys():
            raise BusinessError("部分图片不存在或无权访问", code=40420, status_code=404)
        for group in groups:
            urls = [asset_urls[asset_id] for asset_id in group["input_image_ids"]]
            task_inputs.extend({
                "prompt": group["prompt"], "input_image_url": urls[0], "input_image_urls": urls,
                "input_group_id": group["group_id"], "input_group_name": group["group_name"], "input_group_path": group["group_path"],
            } for _ in range(group["output_count"]))
    elif work_type == "text_to_image":
        if not prompt:
            raise BusinessError("请输入任务提示词", code=40035)
        if requested_output_count > MAX_STANDARD_OUTPUT_COUNT:
            raise BusinessError(f"单次最多生成 {MAX_STANDARD_OUTPUT_COUNT} 张图片", code=40040)
        task_inputs = [{"prompt": prompt, "input_image_url": None} for _ in range(requested_output_count)]
    elif work_type == "batch_generate":
        prompts = [line.strip() for line in prompt.splitlines() if line.strip()]
        if not prompts:
            raise BusinessError("请按行输入至少一条提示词", code=40035)
        task_inputs = [{"prompt": item, "input_image_url": None} for item in prompts]
    else:
        if not prompt:
            raise BusinessError("请输入批量改图说明", code=40036)
        raw_input_image_ids = payload.get("input_image_ids") or []
        if not isinstance(raw_input_image_ids, list) or len(raw_input_image_ids) > MAX_BATCH_EDIT_TASKS:
            raise BusinessError(f"批量改图最多接收 {MAX_BATCH_EDIT_TASKS} 张图片", code=40042)
        input_image_ids = [int(asset_id) for asset_id in raw_input_image_ids]
        if not input_image_ids:
            raise BusinessError("请上传至少一张图片", code=40037)
        matrix_prompts = [line.strip() for line in prompt.splitlines() if line.strip()] if prompt_mode == "matrix" else []
        if prompt_mode == "matrix":
            if not matrix_prompts:
                raise BusinessError("商品套图模式下，请按行填写至少一条场景提示词", code=40039)
            if len(input_image_ids) * len(matrix_prompts) > MAX_BATCH_EDIT_TASKS:
                raise BusinessError(f"商品套图最多生成 {MAX_BATCH_EDIT_TASKS} 个任务", code=40038)
        asset_rows = (
            await db.execute(
                select(image_assets_table.c.id, image_assets_table.c.url).where(
                    image_assets_table.c.user_id == current_user.id,
                    image_assets_table.c.site_id == current_user.site_id,
                    image_assets_table.c.id.in_(input_image_ids),
                )
            )
        ).all()
        asset_urls = {row.id: row.url for row in asset_rows}
        missing_ids = [asset_id for asset_id in input_image_ids if asset_id not in asset_urls]
        if missing_ids:
            raise BusinessError("部分图片不存在或无权访问", code=40420, status_code=404)
        if work_type in {"image_edit", "image_to_image"}:
            if requested_output_count > MAX_STANDARD_OUTPUT_COUNT:
                raise BusinessError(f"单次最多生成 {MAX_STANDARD_OUTPUT_COUNT} 张图片", code=40040)
            task_inputs = [
                {
                    "prompt": prompt,
                    "input_image_url": asset_urls[input_image_ids[0]],
                    "input_image_urls": [asset_urls[asset_id] for asset_id in input_image_ids],
                }
                for _ in range(requested_output_count)
            ]
        elif prompt_mode == "matrix":
            task_inputs = [
                {
                    "prompt": item_prompt,
                    "input_image_url": asset_urls[asset_id],
                }
                for asset_id in input_image_ids
                for item_prompt in matrix_prompts
            ]
        elif prompt_mode == "per_image":
            prompts = [line.strip() for line in prompt.splitlines() if line.strip()]
            if len(prompts) != len(input_image_ids):
                raise BusinessError("一图一词模式下，提示词行数必须和上传图片数量一致", code=40039)
            task_inputs = [
                {"prompt": item_prompt, "input_image_url": asset_urls[asset_id]}
                for asset_id, item_prompt in zip(input_image_ids, prompts, strict=True)
            ]
        else:
            task_inputs = [{"prompt": prompt, "input_image_url": asset_urls[asset_id]} for asset_id in input_image_ids]

    max_batch_tasks = await get_max_batch_tasks(db, current_user.site_id)
    effective_batch_limit = min(max_batch_tasks, MAX_GROUPED_OUTPUTS) if prompt_mode == "grouped" else MAX_BATCH_EDIT_TASKS if work_type == "batch_edit" else min(max_batch_tasks, MAX_BATCH_GENERATE_COUNT)
    if len(task_inputs) > effective_batch_limit:
        raise BusinessError(f"单次批量任务最多 {effective_batch_limit} 条", code=40038)

    if supplied_batch_id and prompt_mode != "grouped":
        request_hash = hashlib.sha256(json.dumps({
            "model_id": model_id, "work_type": work_type, "resolution": resolution,
            "aspect_ratio": aspect_ratio, "quality": quality, **output_options, "task_inputs": task_inputs,
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    created_task_ids: list[int] = []
    background_payloads: list[dict] = []
    sub2_receipts: list[Sub2BalanceReceipt] = []
    team_id = await get_primary_team_id(db, current_user)
    if request_hash is not None:
        # Serialize retries across processes and persist the fingerprint with
        # the tasks. A lost response must not create another debit.
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                         {"key": f"group-batch:{current_user.site_id}:{current_user.id}:{batch_id}"})
        from app.services.image_batch_uploads import find_upload, submission
        uploaded = await find_upload(db, current_user, batch_id)
        if uploaded is not None:
            if uploaded.request_hash != request_hash:
                raise BusinessError("该批次已提交，请使用新批次提交修改后的任务", code=40943, status_code=409)
            return ok(submission(uploaded))
        existing = (await db.execute(
            select(image_tasks_table, image_models_table.c.name.label("model_name"))
            .select_from(outerjoin(image_tasks_table, image_models_table, image_tasks_table.c.model_id == image_models_table.c.id))
            .where(image_tasks_table.c.batch_id == batch_id, image_tasks_table.c.user_id == current_user.id,
                   image_tasks_table.c.site_id == current_user.site_id)
            .order_by(image_tasks_table.c.id.desc()).limit(MAX_BATCH_GENERATE_COUNT)
        )).all()
        if existing:
            if any(row._mapping.get("batch_request_hash") != request_hash for row in existing):
                raise BusinessError("该批次已提交，请使用新批次提交修改后的任务", code=40943, status_code=409)
            return ok({"batch_id": batch_id, "task_count": len(existing), "task_ids": [row.id for row in existing],
                       "tasks": [serialize_task(row._mapping) for row in existing]})
    await ensure_user_image_task_capacity(db, current_user.id, len(task_inputs))
    try:
        for task_input in task_inputs:
            task_no = f"IMG{uuid4().hex[:16].upper()}"
            task_input_urls = [str(url) for url in task_input.get("input_image_urls") or [] if str(url).strip()]
            if not task_input_urls and task_input.get("input_image_url"):
                task_input_urls = [str(task_input["input_image_url"])]
            sub2_receipt = await debit_image_task_credits(db, current_user.id, task_no, credit_cost)
            if sub2_receipt is not None:
                sub2_receipts.append(sub2_receipt)
            result = await db.execute(
                image_tasks_table.insert()
                .values(
                    task_no=task_no,
                    batch_id=batch_id,
                    input_group_id=task_input.get("input_group_id"),
                    input_group_name=task_input.get("input_group_name"),
                    input_group_path=task_input.get("input_group_path"),
                    batch_request_hash=request_hash,
                    site_id=current_user.site_id,
                    team_id=team_id,
                    user_id=current_user.id,
                    model_id=model_id,
                    work_type=work_type,
                    prompt=task_input["prompt"],
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    quality=quality,
                    **output_options,
                    credit_cost=credit_cost,
                    pricing_snapshot=quote_result.data["pricing"],
                    status="queued",
                    timeout_seconds=task_timeout_seconds,
                    disable_retry=task_disable_retry,
                    input_image_url=str(task_input["input_image_url"]) if task_input.get("input_image_url") else None,
                    input_image_urls=dump_input_image_urls(task_input_urls),
                )
                .returning(image_tasks_table.c.id)
            )
            task_id = result.scalar_one()
            created_task_ids.append(task_id)
            background_payloads.append(
                {
                    "task_id": task_id,
                    "site_id": current_user.site_id,
                    "user_id": current_user.id,
                    "model_id": model_id,
                    "prompt": task_input["prompt"],
                    "credit_cost": credit_cost,
                    "timeout_seconds": task_timeout_seconds,
                    "disable_retry": task_disable_retry,
                    "task_no": task_no,
                    "input_image_url": str(task_input["input_image_url"]) if task_input.get("input_image_url") else None,
                    "input_image_urls": task_input_urls,
                    "resolution": resolution,
                    "aspect_ratio": aspect_ratio,
                    "quality": quality, **output_options,
                }
            )

        await db.commit()
    except Exception:
        await compensate_image_task_creation_debits(db, sub2_receipts)
        raise
    background_tasks.add_task(execute_image_task_batch, background_payloads)

    rows = await db.execute(
        select(image_tasks_table, image_models_table.c.name.label("model_name"))
        .select_from(outerjoin(image_tasks_table, image_models_table, image_tasks_table.c.model_id == image_models_table.c.id))
        .where(image_tasks_table.c.id.in_(created_task_ids), image_tasks_table.c.site_id == current_user.site_id)
        .order_by(image_tasks_table.c.created_at.desc(), image_tasks_table.c.id.desc())
        .limit(MAX_GROUPED_OUTPUTS if prompt_mode == "grouped" else MAX_BATCH_EDIT_TASKS if work_type == "batch_edit" else 80)
    )
    return ok(
        {
            "batch_id": batch_id,
            "task_count": len(created_task_ids),
            "task_ids": created_task_ids,
            "tasks": [serialize_task(row._mapping) for row in rows],
        }
    )


async def _get_export_items(task_ids: list[int], batch_id: str, current_user: User, db: AsyncSession) -> list[ExportItem]:
    task_visibility = await visible_task_condition(db, current_user)
    export_conditions = [
        task_visibility,
        or_(image_tasks_table.c.work_type == "batch_generate",
            and_(image_tasks_table.c.status == "succeeded", image_tasks_table.c.output_image_url.is_not(None))),
    ]
    if batch_id:
        export_conditions.append(image_tasks_table.c.batch_id == batch_id)
    else:
        export_conditions.append(image_tasks_table.c.id.in_(task_ids))

    result = await db.execute(
        select(
            image_tasks_table.c.id,
            image_tasks_table.c.task_no,
            image_tasks_table.c.batch_id,
            image_tasks_table.c.input_group_id,
            image_tasks_table.c.input_group_name,
            image_tasks_table.c.input_group_path,
            image_tasks_table.c.output_image_url,
            image_tasks_table.c.output_image_assets,
            image_tasks_table.c.output_expired_at,
            image_tasks_table.c.prompt,
            image_tasks_table.c.input_image_url,
            image_tasks_table.c.created_at,
            image_tasks_table.c.work_type,
            image_tasks_table.c.status,
            image_tasks_table.c.failure_message,
        )
        .where(*export_conditions)
        .order_by(image_tasks_table.c.created_at.asc(), image_tasks_table.c.id.asc())
    )
    rows = result.all()
    if not rows:
        raise BusinessError("没有可导出的结果图", code=40033)
    return [
        ExportItem(
            task_no=f"{row.task_no}-{output_index + 1}" if len(output_urls) > 1 else row.task_no,
            url=output_url,
            work_type=getattr(row, "work_type", ""),
            status=getattr(row, "status", "succeeded"),
            failure_message="图片已过期" if row.output_expired_at else (getattr(row, "failure_message", "") or ""),
            prompt=getattr(row, "prompt", None) or "",
            source=getattr(row, "input_image_url", None) or "",
            batch_id=getattr(row, "batch_id", None) or "",
            group_id=getattr(row, "input_group_id", None) or "",
            group_name=getattr(row, "input_group_name", None) or "",
            group_path=getattr(row, "input_group_path", None) or "",
        )
        for row in rows
        for output_urls in [[asset["url"] for asset in output_assets_from_row(row._mapping)] or [""]]
        for output_index, output_url in enumerate(output_urls)
    ]


@router.post("/image-tasks/export-ticket")
async def create_image_export_ticket(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    raw_task_ids = payload.get("task_ids") or []
    if not isinstance(raw_task_ids, list) or len(raw_task_ids) > MAX_EXPORT_TASK_IDS:
        raise BusinessError(f"一次最多导出 {MAX_EXPORT_TASK_IDS} 个任务", code=40043)
    try:
        task_ids = [int(task_id) for task_id in raw_task_ids]
    except (TypeError, ValueError) as exc:
        raise BusinessError("导出任务编号无效", code=40043) from exc
    batch_id = str(payload.get("batch_id") or "").strip()[:64]
    if not task_ids and not batch_id:
        raise BusinessError("请选择要导出的任务", code=40032)
    visibility = await visible_task_condition(db, current_user)
    query = select(image_tasks_table.c.id).where(visibility, or_(image_tasks_table.c.work_type == "batch_generate", and_(image_tasks_table.c.status == "succeeded", image_tasks_table.c.output_image_url.is_not(None))))
    query = query.where(image_tasks_table.c.batch_id == batch_id) if batch_id else query.where(image_tasks_table.c.id.in_(task_ids))
    if await db.scalar(query.limit(1)) is None:
        raise BusinessError("没有可导出的结果图", code=40033)
    token = create_export_access_token(current_user.id, task_ids=task_ids, batch_id=batch_id)
    return ok({"download_url": f"/image-tasks/export?ticket={token}"})


async def _export_image_tasks_stream(archive: BytesIO):
    try:
        while chunk := archive.read(64 * 1024):
            yield chunk
    finally:
        archive.close()


@router.get("/image-tasks/export")
async def download_image_tasks_export(
    ticket: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    payload = verify_export_access_token(ticket)
    try:
        user_id = int(payload.get("sub"))
        task_ids = [int(task_id) for task_id in payload.get("task_ids") or []]
    except (TypeError, ValueError) as exc:
        raise BusinessError("导出链接无效", code=40101, status_code=401) from exc
    current_user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if current_user is None or not current_user.is_active:
        raise BusinessError("用户不存在或已注销", code=40102, status_code=401)
    batch_id = str(payload.get("batch_id") or "").strip()[:64]
    if not task_ids and not batch_id:
        raise BusinessError("导出链接无效", code=40101, status_code=401)
    items = await _get_export_items(task_ids, batch_id, current_user, db)
    # The export only reads metadata. Do not retain its transaction/connection
    # while downloading files or waiting for an export worker.
    await db.rollback()
    filename = f"zaomeng-outputs-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.zip"
    return StreamingResponse(
        stream_export_archive(items),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )


@router.post("/image-tasks/export")
async def export_image_tasks_legacy(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    raw_task_ids = payload.get("task_ids") or []
    if not isinstance(raw_task_ids, list) or len(raw_task_ids) > MAX_EXPORT_TASK_IDS:
        raise BusinessError(f"一次最多导出 {MAX_EXPORT_TASK_IDS} 个任务", code=40043)
    task_ids = [int(task_id) for task_id in raw_task_ids]
    batch_id = str(payload.get("batch_id") or "").strip()[:64]
    if not task_ids and not batch_id:
        raise BusinessError("请选择要导出的任务", code=40032)
    items = await _get_export_items(task_ids, batch_id, current_user, db)
    await db.rollback()
    filename = f"zaomeng-outputs-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.zip"
    if all(item.work_type == "batch_generate" for item in items):
        return StreamingResponse(stream_export_archive(items), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Accel-Buffering": "no", "Cache-Control": "no-store"})
    archive = await build_export_archive(items)
    return StreamingResponse(
        _export_image_tasks_stream(archive),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def summarize_image_batches(db: AsyncSession, current_user: User, batch_ids: list[str]) -> list[dict]:
    if not batch_ids:
        return []
    visibility = await visible_task_condition(db, current_user)
    child = image_tasks_table.alias("retry_child")
    has_retry = select(child.c.id).where(child.c.retry_of_task_id == image_tasks_table.c.id).exists()
    own_failure = and_(image_tasks_table.c.user_id == current_user.id, image_tasks_table.c.status.in_(("failed", "refunded")))
    result = await db.execute(select(
        image_tasks_table.c.batch_id,
        func.max(image_tasks_table.c.id).label("latest_task_id"),
        func.min(image_tasks_table.c.created_at).label("created_at"),
        func.count().label("task_count"),
        func.count().filter(image_tasks_table.c.status == "pending").label("pending_count"),
        func.count().filter(image_tasks_table.c.status == "queued").label("queued_count"),
        func.count().filter(image_tasks_table.c.status == "running").label("running_count"),
        func.count().filter(image_tasks_table.c.status == "succeeded").label("succeeded_count"),
        func.count().filter(image_tasks_table.c.status.in_(("failed", "refunded"))).label("failed_count"),
        func.count().filter(and_(image_tasks_table.c.status == "succeeded", image_tasks_table.c.output_image_url.is_not(None), image_tasks_table.c.output_expired_at.is_(None))).label("downloadable_count"),
        func.count().filter(and_(own_failure, ~has_retry)).label("retryable_count"),
        func.count().filter(and_(own_failure, has_retry)).label("already_retried_count"),
        func.max(image_tasks_table.c.retry_of_batch_id).label("retry_of_batch_id"),
    ).where(visibility, image_tasks_table.c.batch_id.in_(batch_ids),
            image_tasks_table.c.created_at >= datetime.now(UTC) - timedelta(days=7))
        .group_by(image_tasks_table.c.batch_id).order_by(desc(func.max(image_tasks_table.c.id))))
    items = [dict(row._mapping) for row in result]
    from app.models.image_batch_upload import ImageBatchUpload
    retry_batch_id = ImageBatchUpload.payload["source_batch_id"].as_string()
    retry_jobs = (await db.execute(select(
        ImageBatchUpload.payload["source_batch_id"].as_string().label("batch_id"),
        ImageBatchUpload.status, ImageBatchUpload.error,
    ).where(ImageBatchUpload.site_id == current_user.site_id,
            ImageBatchUpload.user_id == current_user.id,
            ImageBatchUpload.payload["source_batch_id"].as_string().in_(batch_ids))
        .distinct(retry_batch_id).order_by(retry_batch_id, ImageBatchUpload.id.desc()))).all()
    retry_statuses = {row.batch_id: row for row in retry_jobs}
    for item in items:
        if item["batch_id"] in retry_statuses and retry_statuses[item["batch_id"]].status != "submitted":
            job = retry_statuses[item["batch_id"]]
            item.update(retry_submission_status=job.status, retry_submission_error=job.error)
    from app.services.image_batch_uploads import upload_summaries
    present = {item["batch_id"] for item in items}
    items.extend(item for item in await upload_summaries(db, current_user, batch_ids) if item["batch_id"] not in present)
    return items


@router.get("/image-tasks/batches", response_model=StandardResponse[dict])
async def image_task_batches(
    work_type: str = Query(pattern="^(batch_generate|batch_edit)$"),
    limit: int = Query(default=10, ge=1, le=20),
    before_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    visibility = await visible_task_condition(db, current_user)
    latest_id = func.max(image_tasks_table.c.id).label("latest_task_id")
    query = select(image_tasks_table.c.batch_id, latest_id).where(
        visibility, image_tasks_table.c.work_type == work_type,
        image_tasks_table.c.batch_id.is_not(None), image_tasks_table.c.batch_id != "",
        image_tasks_table.c.created_at >= datetime.now(UTC) - timedelta(days=7),
    ).group_by(image_tasks_table.c.batch_id)
    if before_id is not None:
        query = query.having(func.max(image_tasks_table.c.id) < before_id)
    candidates = (await db.execute(query.order_by(desc(latest_id)).limit(limit + 1))).all()
    has_more = len(candidates) > limit
    candidates = candidates[:limit]
    # List and counts use the same seven-day window as task history.
    items = await summarize_image_batches(db, current_user, [row.batch_id for row in candidates])
    if before_id is None and work_type == "batch_generate":
        from app.services.image_batch_uploads import upload_summaries
        pending = await upload_summaries(db, current_user)
        items = pending + items
    return ok({"items": items, "has_more": has_more,
               "next_cursor": candidates[-1].latest_task_id if has_more and candidates else None})


class ImageBatchStatusesRequest(BaseModel):
    batch_ids: list[str] = Field(min_length=1, max_length=20)


@router.post("/image-tasks/batches/statuses", response_model=StandardResponse[list])
async def image_batch_statuses(
    payload: ImageBatchStatusesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    if any(not batch_id.strip() or len(batch_id) > 64 for batch_id in payload.batch_ids):
        raise BusinessError("批次编号无效", code=40043)
    return ok(await summarize_image_batches(db, current_user, list(dict.fromkeys(payload.batch_ids))))


class ImageBatchRetryQuoteRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=64)


class ImageBatchRetryRequest(ImageBatchRetryQuoteRequest):
    request_id: UUID
    task_ids: list[int] = Field(min_length=1, max_length=MAX_BATCH_GENERATE_COUNT)
    quote_token: str = Field(pattern=r"^[a-f0-9]{64}$")


async def retry_source_tasks(db: AsyncSession, current_user: User, batch_id: str, task_ids: list[int] | None = None) -> list[dict]:
    visibility = await visible_task_condition(db, current_user)
    child = image_tasks_table.alias("retry_child")
    query = select(image_tasks_table).where(
        visibility, image_tasks_table.c.batch_id == batch_id,
        image_tasks_table.c.user_id == current_user.id,
        image_tasks_table.c.work_type.in_(("batch_generate", "batch_edit")),
        image_tasks_table.c.status.in_(("failed", "refunded")),
        ~select(child.c.id).where(child.c.retry_of_task_id == image_tasks_table.c.id).exists(),
    )
    if task_ids is not None:
        query = query.where(image_tasks_table.c.id.in_(task_ids))
    rows = (await db.execute(query.order_by(image_tasks_table.c.id).limit(MAX_BATCH_GENERATE_COUNT + 1))).mappings().all()
    if len(rows) > MAX_BATCH_GENERATE_COUNT:
        raise BusinessError(f"单次最多重试 {MAX_BATCH_GENERATE_COUNT} 个任务", code=40038)
    return [dict(row) for row in rows]


async def price_retry_sources(db: AsyncSession, current_user: User, sources: list[dict]) -> tuple[list[dict], str]:
    prices: dict[tuple, dict] = {}
    policies: dict[int, tuple[int, bool]] = {}
    max_inputs: dict[int, int] = {}
    priced = []
    for source in sources:
        spec = (source["model_id"], source["work_type"], source["resolution"], source["aspect_ratio"], source["quality"], source.get("size"), source.get("output_format"))
        if spec not in prices:
            result = await quote(source["model_id"], {**source, "output_count": 1, "n": 1}, current_user, db)
            prices[spec] = result.data
        model_id = source["model_id"]
        if model_id not in policies:
            policies[model_id] = await model_task_policy_snapshot(db, model_id, current_user.site_id)
            max_inputs[model_id] = int(await db.scalar(select(image_models_table.c.max_input_images).where(image_models_table.c.id == model_id, image_models_table.c.site_id == current_user.site_id)) or 0)
        urls = parse_input_image_urls(source["input_image_urls"]) or []
        if not urls and source["input_image_url"]:
            urls = [source["input_image_url"]]
        if len(urls) > max_inputs[model_id]:
            raise BusinessError("原任务参考图数量超过当前模型限制，请重新编辑后提交", code=40043)
        priced.append({**source, "credit_cost": prices[spec]["credit_cost"], "pricing_snapshot": prices[spec]["pricing"], "timeout_seconds": policies[model_id][0], "disable_retry": policies[model_id][1], "input_image_urls": urls})
    fingerprint = [{key: source[key] for key in ("id", "prompt", "model_id", "work_type", "resolution", "aspect_ratio", "quality", "size", "output_format", "input_image_urls", "credit_cost", "pricing_snapshot", "timeout_seconds", "disable_retry")} for source in priced]
    token = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return priced, token


@router.post("/image-tasks/batches/retry-quote", response_model=StandardResponse[dict])
async def image_batch_retry_quote(
    payload: ImageBatchRetryQuoteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    sources = await retry_source_tasks(db, current_user, payload.batch_id)
    if not sources:
        raise BusinessError("没有可重试的本人失败图片；已提交重试的图片请查看处理进度", code=40044)
    priced, token = await price_retry_sources(db, current_user, sources)
    return ok({"batch_id": payload.batch_id, "task_count": len(priced), "task_ids": [source["id"] for source in priced],
               "total_credit_cost": sum(source["credit_cost"] for source in priced), "quote_token": token})


@router.post("/image-tasks/batches/retry", response_model=StandardResponse[dict])
async def retry_image_batch(
    payload: ImageBatchRetryRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    from app.services.image_batch_retries import accept_retry
    return ok(await accept_retry(db, current_user, payload))


async def retry_batch_response(db: AsyncSession, current_user: User, batch_id: str, task_ids: list[int]) -> StandardResponse[dict]:
    rows = (await db.execute(select(image_tasks_table, image_models_table.c.name.label("model_name"))
        .select_from(outerjoin(image_tasks_table, image_models_table, image_tasks_table.c.model_id == image_models_table.c.id))
        .where(image_tasks_table.c.id.in_(task_ids), image_tasks_table.c.site_id == current_user.site_id)
        .order_by(image_tasks_table.c.id.desc()).limit(80))).all()
    return ok({"batch_id": batch_id, "task_count": len(task_ids), "task_ids": task_ids, "tasks": [serialize_task(row._mapping) for row in rows]})


@router.get("/image-tasks", response_model=StandardResponse[list])
async def image_tasks(
    limit: int = Query(default=80, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    batch_id: str | None = Query(default=None, min_length=1, max_length=64),
    status: str | None = Query(default=None, pattern="^(pending|queued|running|succeeded|failed|refunded)$"),
    work_types: Annotated[list[str] | None, Query(max_length=20)] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    try:
        task_visibility = await visible_task_condition(db, current_user)
        query = (
            select(image_tasks_table, image_models_table.c.name.label("model_name"), owner_name_expr())
            .select_from(task_join_with_owner())
            .where(task_visibility, image_tasks_table.c.created_at >= datetime.now(UTC) - timedelta(days=7))
            .order_by(desc(image_tasks_table.c.id))
        )
        if before_id is not None:
            query = query.where(image_tasks_table.c.id < before_id)
        if batch_id is not None:
            query = query.where(image_tasks_table.c.batch_id == batch_id)
        if status is not None:
            query = query.where(image_tasks_table.c.status.in_(("failed", "refunded")) if status == "failed" else image_tasks_table.c.status == status)
        if work_types:
            query = query.where(image_tasks_table.c.work_type.in_(work_types))
        query = query.limit(limit)
        result = await db.execute(query)
    except (OperationalError, ProgrammingError):
        await db.rollback()
        return ok([])
    return ok([serialize_task(row._mapping) for row in result])


@router.post("/image-tasks/statuses", response_model=StandardResponse[list])
async def image_task_statuses(
    payload: ImageTaskStatusesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    task_ids = list(dict.fromkeys(payload.task_ids))
    task_visibility = await visible_task_condition(db, current_user)
    result = await db.execute(
        # Status polling runs every couple of seconds. Do not fetch the full
        # task row (provider snapshots and response summaries can be large)
        # when serialize_task only needs this lightweight projection.
        select(
            image_tasks_table.c.id,
            image_tasks_table.c.status,
            image_tasks_table.c.failure_message,
            image_tasks_table.c.output_image_url,
            image_tasks_table.c.output_image_assets,
            image_tasks_table.c.output_expired_at,
            image_tasks_table.c.output_image_r2_url,
            image_tasks_table.c.output_image_r2_expires_at,
            image_tasks_table.c.worker_started_at,
            image_tasks_table.c.finished_at,
            image_tasks_table.c.provider_http_status,
        )
        # This endpoint is polled every couple of seconds. It only needs task
        # columns, so avoid joining models/users for every status request.
        .select_from(image_tasks_table)
        .where(
            image_tasks_table.c.id.in_(task_ids),
            task_visibility,
        )
    )
    rows_by_id = {int(row._mapping["id"]): serialize_task_status(row._mapping) for row in result}
    return ok([rows_by_id[task_id] for task_id in task_ids if task_id in rows_by_id])


@router.get("/image-tasks/{task_id}/thumbnail", response_class=Response)
async def image_task_thumbnail(
    task_id: int,
    token: str = Query(min_length=16, max_length=64),
    input_index: int | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(
            select(image_tasks_table.c.output_image_url, image_tasks_table.c.output_expired_at, image_tasks_table.c.input_image_url, image_tasks_table.c.input_image_urls).where(
                image_tasks_table.c.id == task_id,
            )
        )
    ).mappings().first()
    # Return this read-only connection before waiting for thumbnail capacity or
    # fetching/decoding a large image. Image requests must not exhaust the API pool.
    await db.rollback()
    if input_index is None and row and row["output_expired_at"]:
        raise BusinessError("图片已过期", code=41040, status_code=410)
    if input_index is None:
        source_url = str(row["output_image_url"] or "") if row else ""
    else:
        inputs = input_urls_from_row(row) if row else []
        source_url = inputs[input_index] if input_index < len(inputs) else ""
    if not source_url or not (
        is_valid_thumbnail_token(task_id, canonicalize_asset_url(source_url), token)
        or is_valid_thumbnail_token(task_id, source_url, token)
    ):
        raise BusinessError("缩略图不存在", code=40431, status_code=404)
    async with image_thumbnail_inflight:
        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(
            image_thumbnail_executor,
            lambda: get_or_create_thumbnail(task_id, source_url),
        )
    return Response(
        content=content,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": f'inline; filename="task-{task_id}-thumbnail.webp"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/image-tasks/{task_id}", response_model=StandardResponse[dict])
async def image_task(task_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    try:
        task_visibility = await visible_task_condition(db, current_user)
        row = (
            await db.execute(
                select(image_tasks_table, image_models_table.c.name.label("model_name"), owner_name_expr())
                .select_from(task_join_with_owner())
                .where(image_tasks_table.c.id == task_id, task_visibility)
            )
        ).first()
    except (OperationalError, ProgrammingError):
        await db.rollback()
        row = None
    if row is None:
        raise BusinessError("任务不存在或无权访问", code=40430, status_code=404)
    return ok(serialize_task(row._mapping))


@router.delete("/image-tasks/{task_id}", response_model=StandardResponse[None])
async def delete_image_task(task_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[None]:
    row = (
        await db.execute(
            select(image_tasks_table.c.id, image_tasks_table.c.status).where(
                image_tasks_table.c.id == task_id,
                image_tasks_table.c.site_id == current_user.site_id,
                image_tasks_table.c.user_id == current_user.id,
                image_tasks_table.c.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise BusinessError("任务不存在或无权访问", code=40430, status_code=404)
    if row.status in {"pending", "queued", "running"}:
        raise BusinessError("任务执行中，暂不能删除", code=40030, status_code=400)
    await db.execute(
        update(image_tasks_table)
        .where(
            image_tasks_table.c.id == task_id,
            image_tasks_table.c.user_id == current_user.id,
            image_tasks_table.c.site_id == current_user.site_id,
            image_tasks_table.c.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.now(UTC))
    )
    await db.commit()
    return ok(None)


@router.get("/gallery", response_model=StandardResponse[list])
async def gallery(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[list]:
    try:
        result = await db.execute(
            select(image_tasks_table, image_models_table.c.name.label("model_name"))
            .select_from(outerjoin(image_tasks_table, image_models_table, image_tasks_table.c.model_id == image_models_table.c.id))
            .where(
                image_tasks_table.c.is_gallery_featured.is_(True),
                image_tasks_table.c.gallery_featured_by.is_not(None),
                image_tasks_table.c.deleted_at.is_(None),
                image_tasks_table.c.site_id == current_user.site_id,
                image_tasks_table.c.status == "succeeded",
                image_tasks_table.c.output_expired_at.is_(None),
                image_tasks_table.c.output_image_url.is_not(None),
            )
            .order_by(image_tasks_table.c.gallery_sort_order.desc(), desc(image_tasks_table.c.gallery_featured_at), desc(image_tasks_table.c.created_at))
            .limit(60)
        )
    except (OperationalError, ProgrammingError):
        await db.rollback()
        return ok([])
    return ok([serialize_gallery_work(row._mapping) for row in result])


@router.get("/works", response_model=StandardResponse[list])
async def works(
    limit: int = Query(default=80, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    try:
        task_visibility = await visible_task_condition(db, current_user)
        work_query = (
            select(
                image_tasks_table.c.id,
                image_tasks_table.c.work_type,
                image_tasks_table.c.aspect_ratio,
                image_tasks_table.c.gallery_title,
                image_tasks_table.c.prompt,
                image_tasks_table.c.input_image_url,
                image_tasks_table.c.input_image_urls,
                image_tasks_table.c.output_image_url,
                image_tasks_table.c.output_image_assets,
                image_tasks_table.c.output_expired_at,
                image_tasks_table.c.output_image_r2_url,
                image_tasks_table.c.output_image_r2_expires_at,
                image_tasks_table.c.is_collected,
                image_tasks_table.c.is_gallery_featured,
                image_tasks_table.c.gallery_featured_by,
                image_tasks_table.c.user_id,
                image_tasks_table.c.created_at,
                image_models_table.c.name.label("model_name"),
                owner_name_expr(),
            )
            .select_from(task_join_with_owner())
            .where(
                task_visibility,
                image_tasks_table.c.status == "succeeded",
                image_tasks_table.c.output_expired_at.is_(None),
                image_tasks_table.c.output_image_url.is_not(None),
            )
            .order_by(desc(image_tasks_table.c.id))
        )
        if before_id is not None:
            work_query = work_query.where(image_tasks_table.c.id < before_id)
        work_query = work_query.limit(limit)
        result = await db.execute(work_query)
    except (OperationalError, ProgrammingError):
        await db.rollback()
        return ok([])
    return ok([serialize_user_work(row._mapping) for row in result])


@router.patch("/works/{work_id}", response_model=StandardResponse[dict])
async def update_work(work_id: int, payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    condition = and_(
        image_tasks_table.c.id == work_id,
        image_tasks_table.c.user_id == current_user.id,
        image_tasks_table.c.site_id == current_user.site_id,
        image_tasks_table.c.deleted_at.is_(None),
    )
    task = (await db.execute(select(image_tasks_table).where(condition).with_for_update())).mappings().first()
    if task is None:
        raise BusinessError("作品不存在或无权访问", code=40440, status_code=404)
    values = {}
    if task.output_expired_at and (payload.get("is_collected") or payload.get("is_recommended")):
        raise BusinessError("图片已过期", code=41040, status_code=410)
    if "is_collected" in payload:
        values["is_collected"] = bool(payload.get("is_collected"))
    if "is_recommended" in payload:
        requested = payload["is_recommended"]
        if not isinstance(requested, bool):
            raise BusinessError("提交审核状态必须为布尔值", code=40030, status_code=400)
        if requested and (task.status != "succeeded" or not task.output_image_url):
            raise BusinessError("只有成功生成的作品才能提交审核", code=40030, status_code=400)
        # featured without an admin ID is a request, never publication. Repeated
        # submissions are idempotent; withdrawal clears any previous approval.
        if not requested or not task.is_gallery_featured:
            values.update(is_gallery_featured=requested, gallery_featured_by=None, gallery_featured_at=None)
    if values:
        await db.execute(update(image_tasks_table).where(condition).values(**values))
        await db.commit()
    row = (
        await db.execute(
            select(image_tasks_table, image_models_table.c.name.label("model_name"))
            .select_from(outerjoin(image_tasks_table, image_models_table, image_tasks_table.c.model_id == image_models_table.c.id))
            .where(condition)
        )
    ).first()
    if row is None:
        raise BusinessError("作品不存在或无权访问", code=40440, status_code=404)
    work = serialize_user_work(row._mapping)
    return ok(work)


@router.delete("/works/{work_id}", response_model=StandardResponse[None])
async def delete_work(work_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[None]:
    await db.execute(delete(image_tasks_table).where(image_tasks_table.c.id == work_id, image_tasks_table.c.user_id == current_user.id, image_tasks_table.c.site_id == current_user.site_id))
    await db.commit()
    return ok(None)
