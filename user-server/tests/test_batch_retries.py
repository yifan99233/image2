import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import func, select, text, update

from app.api.routes import catalog
from app.core.exceptions import BusinessError
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.image_batch_upload import ImageBatchUpload
from app.models.user import User
from app.services import image_batch_retries as retries, image_batch_uploads as uploads
from app.services.sub2_image_billing import _receipt_from_debit_operation
from test_batch_progress import batch_client, seed
from test_batch_groups import sessions
from test_batch_uploads import external_billing


@pytest.fixture
async def retry_client(batch_client):
    yield batch_client


async def failed(sessions, batch="source", statuses=None, **overrides):
    await seed(sessions, batch, statuses or ["failed", "refunded", "succeeded", "running", "queued"],
               work_type="batch_edit", resolution="1k", aspect_ratio="1:1", credit_cost=7,
               input_image_url="https://cdn.test/front.png", input_image_urls=json.dumps(["https://cdn.test/front.png", "https://cdn.test/side.png"]),
               input_group_id="group-A", input_group_name="商品A", input_group_path="素材/商品A", **overrides)


async def preview(client, batch="source"):
    response = await client.post("/image-tasks/batches/retry-quote", json={"batch_id": batch})
    assert response.status_code == 200, response.text
    quote = response.json()["data"]
    return {"batch_id": batch, "task_ids": quote["task_ids"], "quote_token": quote["quote_token"], "request_id": str(uuid4())}, quote


async def snapshot(sessions):
    async with sessions() as db:
        account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == 1))
        rows = (await db.execute(select(catalog.image_tasks_table).order_by(catalog.image_tasks_table.c.id))).mappings().all()
        return [dict(row) for row in rows], account.balance, await db.scalar(select(func.count()).select_from(CreditLedger))


async def job(sessions):
    async with sessions() as db:
        return await db.scalar(select(ImageBatchUpload).order_by(ImageBatchUpload.id.desc()).limit(1))


async def process(sessions):
    await uploads.process_upload((await job(sessions)).id, sessions)


async def billing(sessions, monkeypatch):
    result = await external_billing(sessions, monkeypatch)
    monkeypatch.setattr(retries, "_billing_context", uploads._billing_context)
    return result


async def test_retry_acknowledges_without_billing_and_keeps_batch_ids_counts_and_successes(sessions, retry_client):
    await failed(sessions)
    before, _, _ = await snapshot(sessions)
    request, quote = await preview(retry_client)
    assert quote["task_count"] == 2 and quote["total_credit_cost"] == 14
    response = await retry_client.post("/image-tasks/batches/retry", json=request)
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["batch_id"] == "source" and result["task_ids"] == request["task_ids"] and result["tasks"] == []
    rows, balance, ledgers = await snapshot(sessions)
    assert len(rows) == 5 and balance == 2000 and ledgers == 0
    assert [row["status"] for row in rows] == ["pending", "pending", "succeeded", "running", "queued"]
    await process(sessions)
    rows, balance, ledgers = await snapshot(sessions)
    assert balance == 1986 and ledgers == 2 and len(rows) == 5
    assert [row["id"] for row in rows] == [row["id"] for row in before]
    assert [row["status"] for row in rows] == ["queued", "queued", "succeeded", "running", "queued"]
    assert all(row["batch_id"] == "source" for row in rows)
    assert all(row["task_no"] != before[i]["task_no"] for i, row in enumerate(rows[:2]))
    assert rows[2:] == before[2:]
    assert all(row["input_group_path"] == "素材/商品A" and row["prompt"] == before[i]["prompt"] for i, row in enumerate(rows))
    journal = await job(sessions)
    assert journal.status == "submitted" and "retry_sources" not in journal.payload
    assert [attempt["task_no"] for attempt in journal.payload["previous_attempts"]] == [row["task_no"] for row in before[:2]]
    page = (await retry_client.get("/image-tasks/batches?work_type=batch_edit")).json()["data"]
    assert len(page["items"]) == 1 and page["items"][0]["task_count"] == 5


async def test_concurrent_same_request_and_lost_response_reserve_and_bill_once(sessions, retry_client):
    await failed(sessions)
    request, _ = await preview(retry_client)
    async def submit():
        async with sessions() as db:
            return await catalog.retry_image_batch(catalog.ImageBatchRetryRequest(**request), BackgroundTasks(), await db.get(User, 1), db)
    results = await asyncio.gather(*(submit() for _ in range(5)))
    assert all(result.data["batch_id"] == "source" and result.data["task_ids"] == request["task_ids"] for result in results)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ImageBatchUpload)) == 1
    await process(sessions)
    assert (await snapshot(sessions))[1:] == (1986, 2)
    assert (await retry_client.post("/image-tasks/batches/retry", json=request)).status_code == 200
    await process(sessions)
    assert (await snapshot(sessions))[1:] == (1986, 2)
    request["quote_token"] = "f" * 64
    assert (await retry_client.post("/image-tasks/batches/retry", json=request)).status_code == 409


async def test_different_requests_cannot_retry_reserved_tasks_twice(sessions, retry_client):
    await failed(sessions)
    first, _ = await preview(retry_client)
    second = {**first, "request_id": str(uuid4())}
    responses = await asyncio.gather(*(retry_client.post("/image-tasks/batches/retry", json=value) for value in (first, second)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert (await retry_client.post("/image-tasks/batches/retry-quote", json={"batch_id": "source"})).json()["code"] == 40044


@pytest.mark.parametrize("change", ["price", "model", "references", "recovered"])
async def test_changed_quote_never_reserves_or_bills(sessions, retry_client, change):
    await failed(sessions)
    request, _ = await preview(retry_client)
    async with sessions() as db:
        if change == "price": await db.execute(text("UPDATE image_model_prices SET credit_cost=9 WHERE model_id=5"))
        elif change == "model": await db.execute(text("UPDATE image_models SET is_active=false WHERE id=5"))
        elif change == "references": await db.execute(text("UPDATE image_models SET max_input_images=1 WHERE id=5"))
        else: await db.execute(update(catalog.image_tasks_table).where(catalog.image_tasks_table.c.id == request["task_ids"][0]).values(status="succeeded"))
        await db.commit()
    assert (await retry_client.post("/image-tasks/batches/retry", json=request)).json()["code"] != 0
    rows, balance, ledgers = await snapshot(sessions)
    assert all(row["status"] != "pending" for row in rows) and balance == 2000 and ledgers == 0


async def test_new_failures_do_not_change_confirmed_selection(sessions, retry_client):
    await failed(sessions)
    request, _ = await preview(retry_client)
    async with sessions() as db:
        await db.execute(update(catalog.image_tasks_table).where(catalog.image_tasks_table.c.status == "running").values(status="failed"))
        await db.commit()
    assert (await retry_client.post("/image-tasks/batches/retry", json=request)).status_code == 200
    next_request, quote = await preview(retry_client)
    assert quote["task_count"] == 1 and not set(request["task_ids"]).intersection(next_request["task_ids"])


async def test_insufficient_balance_and_capacity_leave_original_failures(sessions, retry_client, monkeypatch):
    await failed(sessions, statuses=["failed"] * 3)
    async with sessions() as db:
        await db.execute(update(UserCreditAccount).values(balance=10))
        await db.commit()
    request, _ = await preview(retry_client)
    assert (await retry_client.post("/image-tasks/batches/retry", json=request)).json()["code"] == 40030
    assert (await snapshot(sessions))[1:] == (10, 0)
    monkeypatch.setattr(catalog.settings, "image_task_queue_limit_per_user", 2)
    assert (await retry_client.post("/image-tasks/batches/retry", json=request)).json()["code"] == 42911
    assert all(row["status"] == "failed" for row in (await snapshot(sessions))[0])


@pytest.mark.parametrize("source", ["other", "cross-site", "deleted", "succeeded"])
async def test_unowned_cross_site_deleted_successful_batches_cannot_retry(sessions, retry_client, source):
    overrides = {"user_id": 2} if source == "other" else {"site_id": 2} if source == "cross-site" else {}
    await failed(sessions, batch=source, statuses=["succeeded"] if source == "succeeded" else ["failed"], **overrides)
    if source == "deleted":
        async with sessions() as db:
            await db.execute(text("UPDATE image_tasks SET deleted_at=now()")); await db.commit()
    assert (await retry_client.post("/image-tasks/batches/retry-quote", json={"batch_id": source})).json()["code"] == 40044


async def test_each_execution_attempt_refunds_once_while_task_identity_stays_fixed(sessions, retry_client):
    await failed(sessions, statuses=["failed"])
    request, _ = await preview(retry_client)
    result = (await retry_client.post("/image-tasks/batches/retry", json=request)).json()["data"]
    await process(sessions)
    first = (await snapshot(sessions))[0][0]
    async with sessions() as db:
        await db.execute(update(catalog.image_tasks_table).where(catalog.image_tasks_table.c.id == first["id"]).values(status="failed"))
        await catalog.refund_image_task_credits(db, 1, first["task_no"], 7); await db.commit()
        await catalog.refund_image_task_credits(db, 1, first["task_no"], 7); await db.commit()
    assert (await snapshot(sessions))[1:] == (2000, 2)
    request, _ = await preview(retry_client)
    assert (await retry_client.post("/image-tasks/batches/retry", json=request)).json()["data"]["batch_id"] == result["batch_id"]
    await process(sessions)
    rows, balance, ledgers = await snapshot(sessions)
    assert len(rows) == 1 and rows[0]["id"] == first["id"] and rows[0]["task_no"] != first["task_no"]
    assert (balance, ledgers) == (1993, 3)


@pytest.mark.parametrize("count", [250, 2000, 5000])
async def test_bulk_retry_returns_before_one_external_debit_and_preserves_individual_refunds(sessions, retry_client, monkeypatch, count):
    calls, effects, fail = await billing(sessions, monkeypatch)
    await failed(sessions, statuses=["failed"] * count)
    request, _ = await preview(retry_client)
    result = (await retry_client.post("/image-tasks/batches/retry", json=request)).json()["data"]
    assert calls == [] and result["batch_id"] == "source" and len(result["task_ids"]) == count
    assert (await snapshot(sessions))[1:] == (2000, 0)
    fail["debit_ack"] = True
    await process(sessions)
    assert (await job(sessions)).status == "processing"
    assert all(row["status"] == "pending" for row in (await snapshot(sessions))[0])
    await process(sessions)
    assert (await job(sessions)).status == "submitted"
    assert len(calls) == 2 and calls[0][1]["idempotency_key"] == calls[1][1]["idempotency_key"]
    assert len(effects) == 1
    async with sessions() as db:
        rows = (await snapshot(sessions))[0]
        assert len(rows) == count and all(row["status"] == "queued" for row in rows)
        receipt = await _receipt_from_debit_operation(db, rows[0]["task_no"])
        assert str(receipt.amount) == "0.0700"
        monkeypatch.setattr(catalog, "refund_image_task_balance", uploads.refund_image_task_balance)
        await catalog.refund_image_task_credits(db, 1, rows[0]["task_no"], 7); await db.commit()
        await catalog.refund_image_task_credits(db, 1, rows[0]["task_no"], 7); await db.commit()
    assert len(calls) == 3 and (await snapshot(sessions))[2] == count + 1


@pytest.mark.parametrize("failure", ["reject", "materialize"])
async def test_terminal_submission_failure_restores_original_attempt_without_losing_refund_audit(sessions, retry_client, monkeypatch, failure):
    calls, effects, fail = await billing(sessions, monkeypatch)
    await failed(sessions, statuses=["failed"], finished_at=datetime.now(UTC))
    before = await snapshot(sessions)
    request, _ = await preview(retry_client)
    await retry_client.post("/image-tasks/batches/retry", json=request)
    if failure == "reject": fail["reject"] = True
    else: monkeypatch.setattr(uploads, "materialize_tasks", AsyncMock(side_effect=RuntimeError("write failed")))
    await process(sessions)
    assert (await job(sessions)).status == "failed"
    assert await snapshot(sessions) == before
    assert sum(effects.values()) == 0
    assert len(calls) == (1 if failure == "reject" else 2)
    summary = (await retry_client.get("/image-tasks/batches?work_type=batch_edit")).json()["data"]["items"][0]
    assert summary["retry_submission_status"] == "failed" and summary["retry_submission_error"]


async def test_pending_retry_counts_once_toward_capacity_and_has_no_separate_batch_card(sessions, retry_client, monkeypatch):
    await failed(sessions, statuses=["failed"] * 2)
    monkeypatch.setattr(catalog.settings, "image_task_queue_limit_per_user", 3)
    request, _ = await preview(retry_client)
    await retry_client.post("/image-tasks/batches/retry", json=request)
    async with sessions() as db:
        await catalog.ensure_user_image_task_capacity(db, 1, 1)
        with pytest.raises(BusinessError): await catalog.ensure_user_image_task_capacity(db, 1, 2)
    page = (await retry_client.get("/image-tasks/batches?work_type=batch_edit")).json()["data"]["items"]
    assert len(page) == 1 and page[0]["batch_id"] == "source" and page[0]["task_count"] == 2
    assert page[0]["pending_count"] == 2 and page[0]["retry_submission_status"] == "queued"
