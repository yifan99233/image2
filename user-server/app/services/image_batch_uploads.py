"""PostgreSQL-backed intake: acknowledge files before billing or creating tasks.

The billing journal is committed before each external side effect. Provider
idempotency keys survive worker crashes; compensation is a separate phase and
can never lead back to debit. Individual task receipts preserve existing refunds.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import load_only

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.models.agent import AgentConfig
from app.models.image_batch_upload import ImageBatchUpload
from app.services.agent_openapi import AgentAPIError, AgentOpenAPIClient
from app.services.sub2_image_billing import (
    Sub2BalanceReceipt, _billing_context, _record_operation, _to_sub2_amount,
    refund_image_task_balance,
)

logger = logging.getLogger(__name__)
ACTIVE_UPLOAD_STATUSES = ("queued", "processing", "debited", "compensating", "needs_attention")
WORK_UPLOAD_STATUSES = ACTIVE_UPLOAD_STATUSES[:-1]


def parse_manifest(raw: bytes) -> dict:
    from app.api.routes import catalog
    if len(raw) > settings.batch_upload_max_bytes:
        raise BusinessError("提示词文件超过上传大小限制，请拆分后提交", code=41341, status_code=413)
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BusinessError("提示词文件必须是有效的 UTF-8 JSON", code=40041) from exc
    if not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") != 1 or value.get("work_type") != "batch_generate":
        raise BusinessError("提示词文件格式无效", code=40041)
    prompts = value.get("prompts")
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= catalog.MAX_BATCH_GENERATE_COUNT:
        raise BusinessError(f"提示词文件需要包含 1 至 {catalog.MAX_BATCH_GENERATE_COUNT} 条提示词", code=40038)
    if any(not isinstance(p, str) or not p.strip() or len(p) > settings.batch_upload_max_prompt_chars for p in prompts):
        raise BusinessError(f"每条提示词不能为空，且最多 {settings.batch_upload_max_prompt_chars} 个字符", code=40041)
    batch_id = value.get("batch_id")
    if not isinstance(batch_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
        raise BusinessError("批次编号格式错误", code=40043)
    model_id = value.get("model_id")
    if isinstance(model_id, bool) or not isinstance(model_id, int) or model_id <= 0:
        raise BusinessError("模型编号无效", code=40001)
    for key in ("resolution", "aspect_ratio", "quality"):
        if key in value and (not isinstance(value[key], str) or len(value[key]) > 32):
            raise BusinessError("图片规格无效", code=40001)
    folders = value.get("folder_names")
    if folders is not None:
        if not isinstance(folders, list) or len(folders) != len(prompts):
            raise BusinessError("文件夹与提示词数量不匹配", code=40041)
        from app.services.batch_export_reports import validate_folder_name
        for folder in folders:
            validate_folder_name(folder)
    return {"model_id": model_id, "work_type": "batch_generate", "batch_id": batch_id,
            "resolution": value.get("resolution", ""), "aspect_ratio": value.get("aspect_ratio", ""),
            "quality": catalog.normalize_image_quality(value.get("quality")),
            "prompts": [p.strip() for p in prompts], **({"folder_names": folders} if folders is not None else {})}


def manifest_hash(value: dict) -> str:
    # Same canonical representation as the legacy batch endpoint.
    return hashlib.sha256(json.dumps({
        "model_id": value["model_id"], "work_type": "batch_generate",
        "resolution": value["resolution"], "aspect_ratio": value["aspect_ratio"], "quality": value["quality"],
        "task_inputs": [{"prompt": p, "input_image_url": None} for p in value["prompts"]],
        **({"folder_names": value["folder_names"]} if "folder_names" in value else {}),
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def submission(job: ImageBatchUpload) -> dict:
    return {"batch_id": job.batch_id, "task_count": job.task_count, "task_ids": [], "tasks": [],
            "submission_status": job.status, "submission_error": job.error}


async def find_upload(db, user, batch_id):
    return await db.scalar(select(ImageBatchUpload).options(load_only(
        ImageBatchUpload.id, ImageBatchUpload.batch_id, ImageBatchUpload.request_hash,
        ImageBatchUpload.task_count, ImageBatchUpload.status, ImageBatchUpload.error,
    )).where(
        ImageBatchUpload.site_id == user.site_id, ImageBatchUpload.user_id == user.id,
        ImageBatchUpload.batch_id == batch_id,
    ))


async def accept_manifest(db, user, value: dict) -> dict:
    from app.api.routes import catalog
    from app.api.routes.ux import get_max_batch_tasks
    digest = manifest_hash(value)
    # Workspace initialization may commit. Finish it before acquiring the
    # transaction lock that serializes intake retries.
    team_id = await catalog.get_primary_team_id(db, user)
    limit = min(await get_max_batch_tasks(db, user.site_id), catalog.MAX_BATCH_GENERATE_COUNT)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": f"group-batch:{user.site_id}:{user.id}:{value['batch_id']}"})
    existing = await find_upload(db, user, value["batch_id"])
    if existing:
        if existing.request_hash != digest:
            raise BusinessError("该批次已提交，请使用新批次提交修改后的任务", code=40943, status_code=409)
        return submission(existing)
    previous = (await db.execute(select(catalog.image_tasks_table.c.id, catalog.image_tasks_table.c.batch_request_hash).where(
        catalog.image_tasks_table.c.site_id == user.site_id, catalog.image_tasks_table.c.user_id == user.id,
        catalog.image_tasks_table.c.batch_id == value["batch_id"],
    ))).all()
    if previous:
        if any(row.batch_request_hash != digest for row in previous):
            raise BusinessError("该批次已提交，请使用新批次提交修改后的任务", code=40943, status_code=409)
        return {"batch_id": value["batch_id"], "task_count": len(previous), "task_ids": [], "tasks": [], "submission_status": "submitted"}
    count = len(value["prompts"])
    if count > limit:
        raise BusinessError(f"单次批量任务最多 {limit} 条", code=40038)
    quote = await catalog.quote(value["model_id"], {**value, "output_count": 1, "n": 1}, user, db)
    cost = Decimal(str(quote.data["credit_cost"]))
    timeout, disable_retry = await catalog.model_task_policy_snapshot(db, value["model_id"], user.site_id)
    await catalog.ensure_user_image_task_capacity(db, user.id, count)
    context = await _billing_context(db, user.id) if cost > 0 else None
    billing = None
    if context:
        unit = _to_sub2_amount(cost, context.config)
        receipt = Sub2BalanceReceipt(
            site_id=user.site_id, user_id=user.id, agent_user_id=int(context.account.agent_user_id),
            amount=unit * count, debit_idempotency_key=f"image2-batch-debit:{user.site_id}:{user.id}:{value['batch_id']}",
            refund_idempotency_key=f"image2-batch-refund:{user.site_id}:{user.id}:{value['batch_id']}",
            biz_id=value["batch_id"],
        )
        billing = {**asdict(receipt), "amount": str(receipt.amount), "unit_amount": str(unit)}
    else:
        account = await catalog.get_or_create_credit_account_for_update(db, user.id)
        if account.balance < cost * count:
            raise BusinessError("积分余额不足", code=40030)
    job = ImageBatchUpload(site_id=user.site_id, user_id=user.id, team_id=team_id,
                           batch_id=value["batch_id"], request_hash=digest, task_count=count,
                           payload={**value, "credit_cost": str(cost), "pricing_snapshot": quote.data["pricing"], "timeout_seconds": timeout, "disable_retry": disable_retry},
                           billing=billing, status="queued", attempts=0)
    db.add(job)
    await db.commit()
    logger.info("Batch upload accepted job=%s user=%s site=%s tasks=%s", job.id, job.user_id, job.site_id, count)
    return submission(job)


def reserved_upload_count_query(user_id: int):
    return select(func.coalesce(func.sum(ImageBatchUpload.task_count), 0)).where(
        ImageBatchUpload.user_id == user_id, ImageBatchUpload.status.in_(ACTIVE_UPLOAD_STATUSES),
        # Retry intake reserves the existing rows as pending; count them once.
        ImageBatchUpload.payload["source_batch_id"].as_string().is_(None),
    ).scalar_subquery()


def upload_summary(job: ImageBatchUpload) -> dict:
    active = job.status in WORK_UPLOAD_STATUSES
    return {"batch_id": job.batch_id, "latest_task_id": 0, "created_at": job.created_at,
            "task_count": job.task_count, "pending_count": job.task_count if active else 0,
            "queued_count": 0, "running_count": 0, "succeeded_count": 0, "failed_count": 0,
            "downloadable_count": 0, "retryable_count": 0, "already_retried_count": 0,
            "retry_of_batch_id": None, "submission_status": job.status, "submission_error": job.error}


async def upload_summaries(db, user, batch_ids=None) -> list[dict]:
    query = select(ImageBatchUpload).options(load_only(
        ImageBatchUpload.id, ImageBatchUpload.batch_id, ImageBatchUpload.task_count,
        ImageBatchUpload.status, ImageBatchUpload.error, ImageBatchUpload.created_at,
    )).where(ImageBatchUpload.site_id == user.site_id,
                                          ImageBatchUpload.user_id == user.id,
                                          ImageBatchUpload.status != "submitted",
                                          ImageBatchUpload.payload["source_batch_id"].as_string().is_(None))
    if batch_ids is not None:
        query = query.where(ImageBatchUpload.batch_id.in_(batch_ids))
    else:
        query = query.where(ImageBatchUpload.created_at >= datetime.now(UTC) - timedelta(days=30))
    jobs = (await db.scalars(query.order_by(ImageBatchUpload.id.desc()).limit(20))).all()
    return [upload_summary(job) for job in jobs]


def receipt_from_job(job):
    if not job.billing:
        return None
    fields = {key: job.billing[key] for key in Sub2BalanceReceipt.__dataclass_fields__}
    return Sub2BalanceReceipt(**{**fields, "amount": Decimal(fields["amount"])})


async def set_phase(db, job, status, *, error=None, clear_payload=False):
    if status == "failed" and "retry_sources" in job.payload:
        from app.services.image_batch_retries import restore_failed_attempts
        await restore_failed_attempts(db, job)
    job.status = status
    job.error = error
    job.attempts = 0
    job.updated_at = datetime.now(UTC)
    job.next_attempt_at = datetime.now(UTC)
    if clear_payload:
        # Previous attempts remain available as the durable execution and
        # billing audit; only discard the finished retry's working plan.
        job.payload = ({key: job.payload[key] for key in ("source_batch_id", "previous_attempts")}
                       if "source_batch_id" in job.payload else {})
    await db.commit()


async def materialize_tasks(db, job, receipt):
    if "retry_sources" in job.payload:
        from app.services.image_batch_retries import materialize_retry
        return await materialize_retry(db, job, receipt)
    from app.api.routes import catalog
    value = job.payload
    cost = Decimal(str(value["credit_cost"]))
    account = await catalog.get_or_create_credit_account_for_update(db, job.user_id)
    if receipt is None and account.balance < cost * job.task_count:
        raise BusinessError("积分余额不足", code=40030)
    rows = []
    for index, prompt in enumerate(value["prompts"]):
        folder = value.get("folder_names", [])[index] if value.get("folder_names") else None
        task_no = "IMG" + hashlib.sha256(f"{job.site_id}:{job.user_id}:{job.batch_id}:{index}".encode()).hexdigest()[:24].upper()
        rows.append({"task_no": task_no, "batch_id": job.batch_id, "batch_request_hash": job.request_hash,
                     "input_group_name": folder,
                     "input_group_id": "prompt-" + hashlib.sha256(folder.encode()).hexdigest()[:48] if folder else None,
                     "site_id": job.site_id, "team_id": job.team_id, "user_id": job.user_id,
                     "model_id": value["model_id"], "work_type": "batch_generate", "prompt": prompt,
                     "resolution": value["resolution"], "aspect_ratio": value["aspect_ratio"], "quality": value["quality"],
                     "credit_cost": cost, "pricing_snapshot": value.get("pricing_snapshot"), "status": "queued", "timeout_seconds": value["timeout_seconds"],
                     "disable_retry": value["disable_retry"], "input_image_url": None, "input_image_urls": "[]"})
        if cost > 0:
            before = account.balance
            gift = min(account.gift_balance, cost)
            account.balance -= cost
            account.gift_balance -= gift
            account.total_consumed += cost
            account.version += 1
            catalog.add_credit_ledger(db=db, account=account, user_id=job.user_id, direction="debit", amount=cost,
                                      balance_before=before, balance_after=account.balance, biz_type="image_task",
                                      biz_id=task_no, idempotency_key=f"image-task:debit:{task_no}",
                                      description=f"图片任务预扣 {cost} 积分", gift_amount=gift)
        if receipt is not None:
            child = replace(receipt, amount=Decimal(job.billing["unit_amount"]), biz_id=task_no,
                            debit_idempotency_key=f"image2-image-debit:{task_no}",
                            refund_idempotency_key=f"image2-image-refund:{task_no}")
            _record_operation(db, receipt=child, operation="subtract", biz_type="image_task",
                              idempotency_key=child.debit_idempotency_key,
                              notes=f"image2 批次扣费 {receipt.debit_idempotency_key}")
    await db.execute(catalog.image_tasks_table.insert(), rows)
    # Tasks, local ledgers, per-task refund receipts and terminal state commit
    # together. No queued task can run before its debit is durable.
    await set_phase(db, job, "submitted", clear_payload=True)
    logger.info("Batch upload submitted job=%s tasks=%s", job.id, job.task_count)
    catalog.wake_image_task_dispatcher()


async def process_locked_upload(db, job_id: int):
    job = await db.get(ImageBatchUpload, job_id)
    if job is None or job.status not in WORK_UPLOAD_STATUSES:
        return
    receipt = receipt_from_job(job)
    try:
        if job.status == "queued":
            await set_phase(db, job, "processing")
        if job.status == "processing":
            if receipt is not None:
                config = await db.scalar(select(AgentConfig).where(AgentConfig.site_id == receipt.site_id))
                if config is None:
                    raise BusinessError("账户计费服务尚未配置", code=50381, status_code=503)
                client = AgentOpenAPIClient(config)
                await db.commit()
                await asyncio.to_thread(client.subtract_balance, agent_user_id=receipt.agent_user_id,
                                        amount=receipt.amount, idempotency_key=receipt.debit_idempotency_key,
                                        notes=f"image2 批量图片任务 {job.batch_id}")
            await set_phase(db, job, "debited")
        if job.status == "debited":
            try:
                await materialize_tasks(db, job, receipt)
            except Exception as exc:
                await db.rollback()
                job = await db.get(ImageBatchUpload, job_id, populate_existing=True)
                # A disconnect during COMMIT can still have committed. Read
                # terminal state before deciding to compensate.
                if job.status == "submitted":
                    return
                if receipt is None:
                    await set_phase(db, job, "failed", error=exc.message if isinstance(exc, BusinessError) else "任务创建失败，请重新提交", clear_payload=True)
                    return
                await set_phase(db, job, "compensating", error="任务创建失败，正在退还余额")
        if job.status == "compensating":
            await refund_image_task_balance(db, task_no=job.batch_id, receipt=receipt)
            await set_phase(db, job, "failed", error="任务创建失败，余额已退还，请重新提交", clear_payload=True)
    except Exception as exc:
        await db.rollback()
        job = await db.get(ImageBatchUpload, job_id, populate_existing=True)
        if job.status not in WORK_UPLOAD_STATUSES:
            return
        # Only an explicit rejection before an acknowledged debit is terminal.
        # Timeouts, 5xx and ambiguous outcomes retry the SAME persisted key.
        if job.status == "processing" and isinstance(exc, AgentAPIError) and exc.status_code in (400, 401, 402, 403, 404, 422):
            await set_phase(db, job, "failed", error="余额不足或扣费被拒绝，请检查账户后重新提交", clear_payload=True)
            return
        job.attempts += 1
        job.updated_at = datetime.now(UTC)
        job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=min(60, 5 * 2 ** job.attempts))
        job.error = "批次正在重试，请稍候"
        if job.attempts >= settings.batch_upload_worker_max_attempts:
            job.recovery_phase = job.status
            job.status = "needs_attention"
            job.error = "批次处理结果待确认，请联系客服并提供批次编号，避免重复提交"
        await db.commit()
        logger.warning("Batch upload worker failed job=%s phase=%s error_type=%s", job_id, job.status, type(exc).__name__)


async def process_upload(job_id: int, session_factory=None):
    from app.api.routes import catalog
    factory = session_factory or catalog.AsyncSessionLocal
    # A session advisory lock holds across intermediate commits. It releases
    # on disconnect, so another process can recover a crashed worker.
    async with factory.kw["bind"].connect() as connection:
        key = f"image-batch-upload:{job_id}"
        locked = await connection.scalar(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key})
        await connection.commit()
        if not locked:
            return
        try:
            async with factory(bind=connection) as db:
                await process_locked_upload(db, job_id)
        finally:
            await connection.rollback()
            await connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})
            await connection.commit()


async def batch_upload_worker_loop():
    from app.api.routes import catalog
    workers = {}
    try:
        while True:
            try:
                workers = {job_id: task for job_id, task in workers.items() if not task.done()}
                slots = settings.batch_upload_worker_max_inflight - len(workers)
                if slots > 0:
                    async with catalog.AsyncSessionLocal() as db:
                        ids = (await db.scalars(select(ImageBatchUpload.id).where(
                            ImageBatchUpload.status.in_(WORK_UPLOAD_STATUSES),
                            ImageBatchUpload.next_attempt_at <= datetime.now(UTC),
                            ImageBatchUpload.id.not_in(list(workers)),
                        ).order_by(ImageBatchUpload.next_attempt_at, ImageBatchUpload.id).limit(slots * 2))).all()
                    for job_id in ids[:slots]:
                        task = asyncio.create_task(process_upload(job_id))
                        workers[job_id] = task
                        task.add_done_callback(report_worker_error)
            except Exception as exc:
                logger.warning("Batch upload discovery failed error_type=%s", type(exc).__name__)
            await asyncio.sleep(settings.batch_upload_worker_interval_seconds)
    finally:
        for task in workers.values():
            task.cancel()
        await asyncio.gather(*workers.values(), return_exceptions=True)


def report_worker_error(task):
    if not task.cancelled() and task.exception() is not None:
        logger.error("Batch upload worker stopped error_type=%s", type(task.exception()).__name__)
