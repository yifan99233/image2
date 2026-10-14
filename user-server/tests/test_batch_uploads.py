import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update

from app.api.routes import catalog
from app.core.exceptions import BusinessError
from app.models.agent import AgentConfig, Sub2BalanceOperation
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.image_batch_upload import ImageBatchUpload
from app.models.user import User
from app.services import image_batch_uploads as uploads
from app.services.agent_openapi import AgentAPIError
from app.services.sub2_image_billing import _receipt_from_debit_operation
from test_batch_groups import sessions, counts
from test_batch_progress import batch_client


def manifest(count=3):
    return {"version": 1, "work_type": "batch_generate", "batch_id": "batch-" + uuid4().hex,
            "model_id": 5, "resolution": "1k", "aspect_ratio": "1:1", "quality": "auto",
            "prompts": [f"prompt-{i}\nkeep this inner newline" for i in range(count)]}


@pytest.fixture(autouse=True)
async def prepare_model(sessions):
    async with sessions() as db:
        await db.execute(text("UPDATE image_models SET work_type='text_to_image' WHERE id=5"))
        await db.execute(text("UPDATE image_model_prices SET work_type='text_to_image' WHERE model_id=5"))
        await db.execute(update(UserCreditAccount).values(balance=20000))
        await db.commit()


async def accept(sessions, value):
    async with sessions() as db:
        return await uploads.accept_manifest(db, await db.get(User, 1), uploads.parse_manifest(json.dumps(value).encode()))


async def get_job(sessions, batch_id):
    async with sessions() as db:
        return await db.scalar(select(ImageBatchUpload).where(ImageBatchUpload.batch_id == batch_id))


async def test_auto_specs_quote_and_uploaded_tasks_keep_auto_and_original_prompt(sessions, batch_client):
    async with sessions() as db:
        for spec, association, column in (
            ("image_resolution_specs", "image_model_resolutions", "resolution_id"),
            ("image_aspect_ratio_specs", "image_model_aspect_ratios", "aspect_ratio_id"),
        ):
            spec_id = await db.scalar(text(f"INSERT INTO {spec}(site_id,code,label,sort_order,is_active) VALUES(1,'auto','自动（Auto）',0,true) RETURNING id"))
            await db.execute(text(f"INSERT INTO {association}(model_id,{column}) VALUES(5,:id)"), {"id": spec_id})
        await db.execute(text("INSERT INTO image_model_prices(site_id,model_id,work_type,resolution,aspect_ratio,output_count,credit_cost,version,change_reason) VALUES(1,5,'text_to_image','auto','auto',1,7,1,'Auto test')"))
        await db.commit()
        resolutions, ratios, _ = await catalog.model_options(db, 5)
        assert resolutions == ratios == [{"value": "auto", "label": "自动（Auto）"}]
    quote = await batch_client.post('/models/5/quote', json={"work_type": "batch_generate", "resolution": "auto", "aspect_ratio": "auto", "quality": "auto"})
    assert quote.status_code == 200 and quote.json()['data']['credit_cost'] == 7
    value = manifest(1)
    value.update(resolution='auto', aspect_ratio='auto', prompts=['Portrait 2:3; 2048 × 3072; 300 DPI.\nPreserve original wording.'])
    response = await batch_client.post('/image-tasks/batch-upload', files={'manifest': ('prompts.json', json.dumps(value).encode(), 'application/json')})
    assert response.status_code == 202
    job = await get_job(sessions, value['batch_id'])
    await uploads.process_upload(job.id, sessions)
    async with sessions() as db:
        row = (await db.execute(select(catalog.image_tasks_table).where(catalog.image_tasks_table.c.batch_id == value['batch_id']))).mappings().one()
        assert row['resolution'] == row['aspect_ratio'] == row['quality'] == 'auto'
        assert row['prompt'] == value['prompts'][0] and row['credit_cost'] == 7


async def test_500_long_prompts_acknowledge_without_billing_then_bulk_create_and_reload(sessions, batch_client):
    value = manifest(500)
    value["prompts"] = [f"{i}:" + "完整长提示词内容 " * 600 + "\n第二段保留换行" for i in range(500)]
    raw = json.dumps(value, ensure_ascii=False).encode()
    assert 1_000_000 < len(raw) < uploads.settings.batch_upload_max_bytes
    response = await batch_client.post("/image-tasks/batch-upload", files={"manifest": ("prompts.json", raw, "application/json")})
    assert response.status_code == 202
    accepted = response.json()["data"]
    assert accepted["submission_status"] == "queued" and accepted["task_count"] == 500 and accepted["tasks"] == []
    assert await counts(sessions) == (0, 0, 20000, 20)
    page = (await batch_client.get("/image-tasks/batches?work_type=batch_generate")).json()["data"]
    assert page["items"][0]["pending_count"] == 500
    job = await get_job(sessions, value["batch_id"])
    await uploads.process_upload(job.id, sessions)
    assert await counts(sessions) == (500, 500, 16500, 0)
    job = await get_job(sessions, value["batch_id"])
    assert job.status == "submitted" and job.payload == {}
    async with sessions() as db:
        prompts = (await db.scalars(select(catalog.image_tasks_table.c.prompt).order_by(catalog.image_tasks_table.c.id))).all()
        assert prompts == value["prompts"]
    statuses = (await batch_client.post("/image-tasks/batches/statuses", json={"batch_ids": [job.batch_id]})).json()["data"]
    assert statuses[0]["queued_count"] == 500 and "submission_status" not in statuses[0]
    await uploads.process_upload(job.id, sessions)
    assert await counts(sessions) == (500, 500, 16500, 0)


async def test_concurrent_upload_retries_and_legacy_endpoint_share_idempotency(sessions):
    value = manifest()
    value["prompts"] = ["one", "two", "three"]
    accepted = await asyncio.gather(*(accept(sessions, value) for _ in range(5)))
    assert all(item["batch_id"] == value["batch_id"] for item in accepted)
    job = await get_job(sessions, value["batch_id"])
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ImageBatchUpload)) == 1
        legacy = await catalog.create_batch_image_tasks({**value, "prompt": "one\ntwo\nthree"}, None, await db.get(User, 1), db)
        assert legacy.data["submission_status"] == "queued"
    await asyncio.gather(*(uploads.process_upload(job.id, sessions) for _ in range(5)))
    assert await counts(sessions) == (3, 3, 19979, 0)
    assert (await accept(sessions, value))["submission_status"] == "submitted"
    value["prompts"][0] = "changed"
    with pytest.raises(BusinessError) as caught:
        await accept(sessions, value)
    assert caught.value.status_code == 409


async def test_2000_prompts_create_in_one_transaction_and_enforce_count_limit(sessions):
    value = manifest(2000)
    await accept(sessions, value)
    job = await get_job(sessions, value["batch_id"])
    await uploads.process_upload(job.id, sessions)
    assert await counts(sessions) == (2000, 2000, 6000, 0)
    assert (await get_job(sessions, job.batch_id)).status == "submitted"


async def test_20000_named_prompts_persist_folders_and_idempotency(sessions):
    value = manifest(20000)
    value["folder_names"] = [f"【XMAS-SER-{i // 20 + 1:03d}】" for i in range(20000)]
    async with sessions() as db:
        await db.execute(update(UserCreditAccount).values(balance=200000))
        await db.commit()
    await accept(sessions, value)
    job = await get_job(sessions, value["batch_id"])
    changed = {**value, "folder_names": ["【different】"] * 20000}
    with pytest.raises(BusinessError) as caught:
        await accept(sessions, changed)
    assert caught.value.status_code == 409
    await uploads.process_upload(job.id, sessions)
    assert (await get_job(sessions, job.batch_id)).status == "submitted"
    async with sessions() as db:
        rows = (await db.execute(select(catalog.image_tasks_table.c.prompt, catalog.image_tasks_table.c.input_group_name)
                                 .order_by(catalog.image_tasks_table.c.id))).all()
    assert len(rows) == 20000
    assert [row.prompt for row in rows] == value["prompts"]
    assert [row.input_group_name for row in rows] == value["folder_names"]
    assert await counts(sessions) == (20000, 20000, 60000, 0)


@pytest.mark.parametrize("folders", [["【one】"], ["../bad"] * 3, [None] * 3, ["x" * 121] * 3])
async def test_invalid_folder_metadata_never_bills(sessions, folders):
    value = {**manifest(), "folder_names": folders}
    with pytest.raises(BusinessError):
        await accept(sessions, value)
    assert await counts(sessions) == (0, 0, 20000, 20)


async def test_background_loop_discovers_persisted_upload_after_restart(sessions, monkeypatch):
    value = manifest()
    await accept(sessions, value)
    monkeypatch.setattr(uploads.settings, "batch_upload_worker_interval_seconds", 0.1)
    worker = asyncio.create_task(uploads.batch_upload_worker_loop())
    try:
        for _ in range(40):
            if (await get_job(sessions, value["batch_id"])).status == "submitted":
                break
            await asyncio.sleep(0.05)
        assert (await get_job(sessions, value["batch_id"])).status == "submitted"
        assert await counts(sessions) == (3, 3, 19979, 0)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_reserved_uploads_count_against_queue_capacity_before_tasks_exist(sessions, monkeypatch):
    monkeypatch.setattr(uploads.settings, "image_task_queue_limit_per_user", 6)
    await asyncio.gather(accept(sessions, manifest()), accept(sessions, manifest()))
    with pytest.raises(BusinessError) as caught:
        await accept(sessions, manifest(1))
    assert caught.value.status_code == 429
    async with sessions() as db:
        with pytest.raises(BusinessError):
            await catalog.ensure_user_image_task_capacity(db, 1, 1)
    assert await counts(sessions) == (0, 0, 20000, 20)


@pytest.mark.parametrize("change", ["empty", "too_many", "not_string", "empty_prompt", "too_long", "bad_model", "bad_spec", "bad_batch", "bad_version"])
async def test_invalid_upload_does_not_persist_or_bill(sessions, batch_client, change):
    value = manifest()
    if change == "empty": value["prompts"] = []
    elif change == "too_many": value["prompts"] = ["p"] * (catalog.MAX_BATCH_GENERATE_COUNT + 1)
    elif change == "not_string": value["prompts"] = [42]
    elif change == "empty_prompt": value["prompts"] = [" "]
    elif change == "too_long": value["prompts"] = ["a" * (uploads.settings.batch_upload_max_prompt_chars + 1)]
    elif change == "bad_model": value["model_id"] = True
    elif change == "bad_spec": value["quality"] = {}
    elif change == "bad_batch": value["batch_id"] = "../oops"
    elif change == "bad_version": value["version"] = True
    response = await batch_client.post("/image-tasks/batch-upload", files={"manifest": ("p.json", json.dumps(value).encode())})
    assert response.status_code == 400
    assert await counts(sessions) == (0, 0, 20000, 20)


async def test_oversize_bad_utf8_and_cross_owner_status_are_rejected(sessions, batch_client, monkeypatch):
    monkeypatch.setattr(uploads.settings, "batch_upload_max_bytes", 1024)
    for raw, status in [(b"a" * 1025, 413), (b"\xff", 400), (b"[]", 400)]:
        response = await batch_client.post("/image-tasks/batch-upload", files={"manifest": ("p.json", raw)})
        assert response.status_code == status
    value = manifest(1)
    await accept(sessions, value)
    async with sessions() as db:
        assert await uploads.upload_summaries(db, SimpleNamespace(id=2, site_id=1), [value["batch_id"]]) == []
        assert await uploads.upload_summaries(db, SimpleNamespace(id=1, site_id=2), [value["batch_id"]]) == []


async def external_billing(sessions, monkeypatch):
    async with sessions() as db:
        config = AgentConfig(site_id=1, is_enabled=True, image_billing_enabled=True, base_url="https://billing.invalid",
                             admin_api_key="test-not-a-secret", credit_to_agent_rate=100)
        db.add(config)
        await db.commit()
    monkeypatch.setattr(uploads, "_billing_context", AsyncMock(return_value=SimpleNamespace(config=config, account=SimpleNamespace(agent_user_id=321))))
    calls, effects = [], {}
    fail = {"debit_ack": False, "refund_ack": False, "reject": False}
    class Client:
        def __init__(self, config): pass
        def subtract_balance(self, **kwargs):
            calls.append(("debit", kwargs))
            if fail["reject"]: raise AgentAPIError("insufficient", status_code=402)
            effects.setdefault(kwargs["idempotency_key"], -kwargs["amount"])
            if fail["debit_ack"]:
                fail["debit_ack"] = False
                raise AgentAPIError("response lost")
        def add_balance(self, **kwargs):
            calls.append(("refund", kwargs))
            effects.setdefault(kwargs["idempotency_key"], kwargs["amount"])
            if fail["refund_ack"]:
                fail["refund_ack"] = False
                raise AgentAPIError("response lost")
    monkeypatch.setattr(uploads, "AgentOpenAPIClient", Client)
    import app.services.sub2_image_billing as billing
    monkeypatch.setattr(billing, "AgentOpenAPIClient", Client)
    return calls, effects, fail


async def test_lost_debit_response_recovers_same_key_and_per_task_refunds_remain_correct(sessions, monkeypatch):
    calls, effects, fail = await external_billing(sessions, monkeypatch)
    value = manifest(500)
    await accept(sessions, value)
    job = await get_job(sessions, value["batch_id"])
    fail["debit_ack"] = True
    await uploads.process_upload(job.id, sessions)
    assert (await get_job(sessions, job.batch_id)).status == "processing"
    assert await counts(sessions) == (0, 0, 20000, 20)
    await uploads.process_upload(job.id, sessions)
    assert (await get_job(sessions, job.batch_id)).status == "submitted"
    assert len(effects) == 1 and list(effects.values()) == [Decimal("-35.0000")]
    assert calls[0][1]["idempotency_key"] == calls[1][1]["idempotency_key"]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Sub2BalanceOperation)) == 500
        task_no = await db.scalar(select(catalog.image_tasks_table.c.task_no).order_by(catalog.image_tasks_table.c.id))
        receipt = await _receipt_from_debit_operation(db, task_no)
        assert receipt.amount == Decimal("0.0700") and receipt.agent_user_id == 321
        monkeypatch.setattr(catalog, "refund_image_task_balance", uploads.refund_image_task_balance)
        await catalog.refund_image_task_credits(db, 1, task_no, 7)
        await db.commit()
        await catalog.refund_image_task_credits(db, 1, task_no, 7)
        await db.commit()
    assert sum(effects.values()) == Decimal("-34.9300")
    assert await counts(sessions) == (500, 501, 16507, 7)


async def test_failed_materialization_durable_compensation_never_redebits(sessions, monkeypatch):
    calls, effects, fail = await external_billing(sessions, monkeypatch)
    value = manifest()
    await accept(sessions, value)
    job = await get_job(sessions, value["batch_id"])
    monkeypatch.setattr(uploads, "materialize_tasks", AsyncMock(side_effect=RuntimeError("DB insert fails")))
    fail["refund_ack"] = True
    await uploads.process_upload(job.id, sessions)
    assert (await get_job(sessions, job.batch_id)).status == "compensating"
    await uploads.process_upload(job.id, sessions)
    assert (await get_job(sessions, job.batch_id)).status == "failed"
    assert [kind for kind, _ in calls] == ["debit", "refund", "refund"]
    assert sum(effects.values()) == 0
    assert await counts(sessions) == (0, 0, 20000, 20)
    await uploads.process_upload(job.id, sessions)
    assert len(calls) == 3


async def test_failure_after_bulk_inserts_rolls_back_all_tasks_and_local_ledgers(sessions, monkeypatch):
    calls, effects, fail = await external_billing(sessions, monkeypatch)
    value = manifest(500)
    await accept(sessions, value)
    job = await get_job(sessions, value["batch_id"])
    original = uploads.set_phase
    async def fail_before_commit(db, job, status, **kwargs):
        if status == "submitted":
            assert await db.scalar(select(func.count()).select_from(catalog.image_tasks_table)) == 500
            raise RuntimeError("commit failed")
        await original(db, job, status, **kwargs)
    monkeypatch.setattr(uploads, "set_phase", fail_before_commit)
    await uploads.process_upload(job.id, sessions)
    assert (await get_job(sessions, job.batch_id)).status == "failed"
    assert await counts(sessions) == (0, 0, 20000, 20)
    assert sum(effects.values()) == 0
    assert [kind for kind, _ in calls] == ["debit", "refund"]


async def test_restart_after_acknowledged_debit_and_wallet_changes_uses_frozen_plan(sessions, monkeypatch):
    calls, effects, fail = await external_billing(sessions, monkeypatch)
    value = manifest()
    await accept(sessions, value)
    job = await get_job(sessions, value["batch_id"])
    # Simulate crash after debit acknowledgement was journaled.
    async with sessions() as db:
        await db.execute(update(ImageBatchUpload).where(ImageBatchUpload.id == job.id).values(status="debited"))
        await db.execute(update(AgentConfig).values(credit_to_agent_rate=200))
        await db.commit()
    await uploads.process_upload(job.id, sessions)
    assert calls == []
    async with sessions() as db:
        receipt = await _receipt_from_debit_operation(db, await db.scalar(select(catalog.image_tasks_table.c.task_no)))
        assert receipt.amount == Decimal("0.0700") and receipt.agent_user_id == 321


async def test_explicit_billing_rejection_and_ambiguous_retries_stop_safely(sessions, monkeypatch):
    calls, effects, fail = await external_billing(sessions, monkeypatch)
    value = manifest()
    await accept(sessions, value)
    job = await get_job(sessions, value["batch_id"])
    fail["reject"] = True
    await uploads.process_upload(job.id, sessions)
    assert (await get_job(sessions, job.batch_id)).status == "failed" and not effects
    value = manifest()
    await accept(sessions, value)
    job = await get_job(sessions, value["batch_id"])
    fail["reject"] = False
    for _ in range(uploads.settings.batch_upload_worker_max_attempts):
        fail["debit_ack"] = True
        await uploads.process_upload(job.id, sessions)
    job = await get_job(sessions, job.batch_id)
    assert job.status == "needs_attention" and job.recovery_phase == "processing"
    assert len(effects) == 1 and await counts(sessions) == (0, 0, 20000, 20)
    previous = len(calls)
    await uploads.process_upload(job.id, sessions)
    assert len(calls) == previous
