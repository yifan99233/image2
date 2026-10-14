"""Durable retry intake that preserves the original task and batch identities."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import bindparam, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.models.image_batch_upload import ImageBatchUpload
from app.models.user import User
from app.services import image_batch_uploads as uploads
from app.services.sub2_image_billing import Sub2BalanceReceipt, _billing_context, _record_operation, _to_sub2_amount

if TYPE_CHECKING:
    from app.api.routes.catalog import ImageBatchRetryRequest

# The intake journal also retains the previous execution/billing attempt.
ATTEMPT_FIELDS = (
    "task_no", "status", "failure_message", "finished_at", "worker_started_at",
    "worker_heartbeat_at", "deadline_at", "provider_request_id", "provider_request_snapshot",
    "provider_response_summary", "provider_http_status", "timeout_seconds", "disable_retry",
    "credit_cost", "pricing_snapshot",
)
DATE_FIELDS = {"finished_at", "worker_started_at", "worker_heartbeat_at", "deadline_at"}


def response(job: ImageBatchUpload) -> dict:
    return {"batch_id": job.payload["source_batch_id"], "task_count": job.task_count,
            "task_ids": [item["id"] for item in job.payload["previous_attempts"]],
            "tasks": [], "submission_status": job.status, "submission_error": job.error}


def encode_journal_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported retry journal value: {type(value).__name__}")


async def accept_retry(db: AsyncSession, user: User, payload: ImageBatchRetryRequest) -> dict:
    from app.api.routes import catalog
    ids = sorted(set(payload.task_ids))
    if len(ids) != len(payload.task_ids) or any(task_id < 1 for task_id in ids):
        raise BusinessError("重试任务编号无效", code=40043)
    intake_id = "retry-" + hashlib.sha256(f"{user.site_id}:{user.id}:{payload.request_id}".encode()).hexdigest()[:32]
    digest = hashlib.sha256(json.dumps({"source_batch": payload.batch_id, "task_ids": ids,
                                      "quote_token": payload.quote_token}, sort_keys=True).encode()).hexdigest()
    team_id = await catalog.get_primary_team_id(db, user)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": f"batch-retry:{user.site_id}:{user.id}:{payload.batch_id}"})
    existing = await uploads.find_upload(db, user, intake_id)
    if existing:
        if existing.request_hash != digest:
            raise BusinessError("该重试请求已提交，不能修改请求内容", code=40944, status_code=409)
        # find_upload deliberately loads only small columns; load the journal
        # explicitly for this idempotent response.
        await db.refresh(existing, ["payload"])
        return response(existing)
    legacy = (await db.execute(select(catalog.image_tasks_table.c.id, catalog.image_tasks_table.c.batch_request_hash)
                              .where(catalog.image_tasks_table.c.batch_id == intake_id,
                                     catalog.image_tasks_table.c.user_id == user.id,
                                     catalog.image_tasks_table.c.site_id == user.site_id))).all()
    if legacy:
        if any(row.batch_request_hash != digest for row in legacy):
            raise BusinessError("该重试请求已提交，不能修改请求内容", code=40944, status_code=409)
        return (await catalog.retry_batch_response(db, user, intake_id, [row.id for row in legacy])).data
    sources = await catalog.retry_source_tasks(db, user, payload.batch_id, ids)
    if [source["id"] for source in sources] != ids:
        raise BusinessError("失败任务已变化或已提交重试，请重新确认", code=40944, status_code=409)
    priced, token = await catalog.price_retry_sources(db, user, sources)
    if token != payload.quote_token:
        raise BusinessError("模型价格或任务规格已变化，请重新确认重试费用", code=40944, status_code=409)
    if len(priced) > await catalog.get_max_batch_tasks(db, user.site_id):
        raise BusinessError("重试数量超过当前站点批次限制", code=40038)
    await catalog.ensure_user_image_task_capacity(db, user.id, len(priced))
    total = sum((Decimal(str(source["credit_cost"])) for source in priced), Decimal(0))
    context = await _billing_context(db, user.id) if total > 0 else None
    billing = None
    if context:
        units = [_to_sub2_amount(Decimal(str(source["credit_cost"])), context.config)
                 if source["credit_cost"] > 0 else Decimal(0) for source in priced]
        receipt = Sub2BalanceReceipt(
            site_id=user.site_id, user_id=user.id, agent_user_id=int(context.account.agent_user_id),
            amount=sum(units), debit_idempotency_key=f"image2-batch-debit:{user.site_id}:{user.id}:{intake_id}",
            refund_idempotency_key=f"image2-batch-refund:{user.site_id}:{user.id}:{intake_id}", biz_id=intake_id,
        )
        billing = {**asdict(receipt), "amount": str(receipt.amount), "unit_amounts": [str(unit) for unit in units]}
    else:
        account = await catalog.get_or_create_credit_account_for_update(db, user.id)
        if account.balance < total:
            raise BusinessError("积分余额不足", code=40030)
    previous = []
    plans = []
    for index, source in enumerate(priced):
        previous.append({"id": source["id"], **{key: sources[index].get(key) for key in ATTEMPT_FIELDS}})
        plans.append({"id": source["id"], "task_no": "IMG" + hashlib.sha256(f"{intake_id}:{index}".encode()).hexdigest()[:24].upper(),
                      "credit_cost": str(source["credit_cost"]), "pricing_snapshot": source["pricing_snapshot"],
                      "timeout_seconds": source["timeout_seconds"], "disable_retry": source["disable_retry"]})
    # Reserve the existing failed rows atomically. Pending tasks cannot be
    # dispatched until their debit and individual refund receipts commit.
    reserved = await db.execute(update(catalog.image_tasks_table).where(
        catalog.image_tasks_table.c.id.in_(ids), catalog.image_tasks_table.c.status.in_(("failed", "refunded")),
    ).values(status="pending", failure_message=None, finished_at=None).returning(catalog.image_tasks_table.c.id))
    if set(reserved.scalars().all()) != set(ids):
        raise BusinessError("失败任务已变化，请重新确认", code=40944, status_code=409)
    journal = json.loads(json.dumps({"source_batch_id": payload.batch_id,
                                    "retry_sources": plans, "previous_attempts": previous},
                                   default=encode_journal_value))
    job = ImageBatchUpload(site_id=user.site_id, user_id=user.id, team_id=team_id,
                           batch_id=intake_id, request_hash=digest, task_count=len(ids),
                           payload=journal, billing=billing, status="queued", attempts=0)
    db.add(job)
    await db.commit()
    return response(job)


async def restore_failed_attempts(db: AsyncSession, job: ImageBatchUpload) -> None:
    from app.api.routes import catalog
    for attempt in job.payload["previous_attempts"]:
        values = {key: attempt[key] for key in ATTEMPT_FIELDS}
        for key in DATE_FIELDS:
            if values[key]:
                values[key] = datetime.fromisoformat(values[key])
        await db.execute(update(catalog.image_tasks_table).where(
            catalog.image_tasks_table.c.id == attempt["id"],
            catalog.image_tasks_table.c.user_id == job.user_id,
            catalog.image_tasks_table.c.site_id == job.site_id,
            catalog.image_tasks_table.c.status == "pending",
            catalog.image_tasks_table.c.task_no == attempt["task_no"],
        ).values(**values))


async def materialize_retry(db: AsyncSession, job: ImageBatchUpload, receipt: Sub2BalanceReceipt | None) -> None:
    from app.api.routes import catalog
    plans = job.payload["retry_sources"]
    ids = [plan["id"] for plan in plans]
    current = (await db.execute(select(catalog.image_tasks_table.c.id, catalog.image_tasks_table.c.status)
                               .where(catalog.image_tasks_table.c.id.in_(ids),
                                      catalog.image_tasks_table.c.user_id == job.user_id,
                                      catalog.image_tasks_table.c.site_id == job.site_id)
                               .with_for_update())).all()
    if len(current) != len(plans) or any(row.status != "pending" for row in current):
        raise BusinessError("重试任务状态已变化", code=40944, status_code=409)
    total = sum((Decimal(plan["credit_cost"]) for plan in plans), Decimal(0))
    account = await catalog.get_or_create_credit_account_for_update(db, job.user_id)
    if receipt is None and account.balance < total:
        raise BusinessError("积分余额不足", code=40030)
    rows = []
    for index, plan in enumerate(plans):
        cost = Decimal(plan["credit_cost"])
        if cost > 0:
            before = account.balance
            gift = min(account.gift_balance, cost)
            account.balance -= cost
            account.gift_balance -= gift
            account.total_consumed += cost
            account.version += 1
            catalog.add_credit_ledger(db=db, account=account, user_id=job.user_id, direction="debit", amount=cost,
                                      balance_before=before, balance_after=account.balance, biz_type="image_task",
                                      biz_id=plan["task_no"], idempotency_key=f"image-task:debit:{plan['task_no']}",
                                      description=f"图片任务重试预扣 {cost} 积分", gift_amount=gift)
        if receipt is not None and cost > 0:
            child = replace(receipt, amount=Decimal(job.billing["unit_amounts"][index]), biz_id=plan["task_no"],
                            debit_idempotency_key=f"image2-image-debit:{plan['task_no']}",
                            refund_idempotency_key=f"image2-image-refund:{plan['task_no']}")
            _record_operation(db, receipt=child, operation="subtract", biz_type="image_task",
                              idempotency_key=child.debit_idempotency_key, notes=f"image2 重试扣费 {receipt.debit_idempotency_key}")
        rows.append({"retry_task_id": plan["id"], **{key: plan[key] for key in (
            "task_no", "credit_cost", "pricing_snapshot", "timeout_seconds", "disable_retry")}})
    statement = update(catalog.image_tasks_table).where(catalog.image_tasks_table.c.id == bindparam("retry_task_id")).values(
        task_no=bindparam("task_no"), credit_cost=bindparam("credit_cost"), pricing_snapshot=bindparam("pricing_snapshot"),
        timeout_seconds=bindparam("timeout_seconds"), disable_retry=bindparam("disable_retry"),
        status="queued", worker_started_at=None, worker_heartbeat_at=None, deadline_at=None,
        provider_request_id=None, provider_request_snapshot=None, provider_response_summary=None, provider_http_status=None,
    )
    await db.execute(statement, rows)
    await uploads.set_phase(db, job, "submitted", clear_payload=True)
    catalog.wake_image_task_dispatcher()
