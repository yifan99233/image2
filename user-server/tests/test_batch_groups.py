import asyncio
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import BackgroundTasks
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.api.routes import catalog, catalog_exports
from app.api.routes.batch_groups import validate_batch_groups
from app.core.exceptions import BusinessError
from app.db.session import get_db
from app.main import app
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.image_asset import ImageAsset
from app.models.user import User


def payload():
    return {"work_type": "batch_edit", "model_id": 5, "prompt": "", "prompt_mode": "grouped", "batch_id": "batch-" + uuid4().hex,
            "resolution": "1k", "aspect_ratio": "1:1", "quality": "auto", "output_count": 1, "input_image_ids": [],
            "groups": [{"group_id": "group-A", "group_name": "商品A", "group_path": "素材/商品A", "prompt": "白底\n保留细节", "input_image_ids": [2, 1], "output_count": 2},
                       {"group_id": "group-B", "group_name": "商品B", "prompt": "客厅场景", "input_image_ids": [3], "output_count": 1}]}


@pytest.fixture
async def sessions(monkeypatch):
    # Bootstrap the shared test DB with both services' baseline migrations.
    # Per-test schemas clone those PostgreSQL definitions, including defaults.
    bootstrap = create_async_engine(os.environ["TEST_DATABASE_URL"])
    schema = "batch_groups_" + uuid4().hex
    async with bootstrap.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA {schema}'))
        tables = [row[0] for row in (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))).all()]
        assert "image_tasks" in tables, "Apply the user-server migrations to the isolated TEST_DATABASE_URL first"
        for table in tables:
            await conn.execute(text(f'CREATE TABLE {schema}."{table}" (LIKE public."{table}" INCLUDING ALL)'))
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add_all([User(id=1, site_id=1, username="batch-test", email="batch@test.invalid", password_hash="unused", active_team_id=1),
                    User(id=2, site_id=1, username="other-test", email="other@test.invalid", password_hash="unused")])
        await db.flush()
        db.add(UserCreditAccount(user_id=1, balance=2000, gift_balance=20))
        for asset_id in range(1, 5):
            db.add(ImageAsset(id=asset_id, user_id=1 if asset_id < 4 else 2, site_id=1, storage_key=f"test/{asset_id}.png", url=f"https://cdn.test/{asset_id}.png", mime_type="image/png", size_bytes=5, sha256=str(asset_id)*64))
        db.add(ImageAsset(id=5, user_id=1, site_id=2, storage_key="test/5.png", url="https://cdn.test/5.png", mime_type="image/png", size_bytes=5, sha256="5"*64))
        await db.execute(text("INSERT INTO image_model_providers(id,site_id,name,code,base_url) VALUES(1,1,'test','test','https://provider.invalid')"))
        await db.execute(catalog.image_models_table.insert().values(id=5, site_id=1, provider_id=1, name="test model", code="group-test", vendor_model="test", work_type="image_edit", max_input_images=2, is_active=True, is_public=True))
        await db.execute(text("INSERT INTO image_model_prices(site_id,model_id,work_type,resolution,aspect_ratio,output_count,credit_cost,version,change_reason) VALUES(1,5,'image_edit','1k','1:1',1,7,1,'test')"))
        await db.execute(text("INSERT INTO user_teams(id,site_id,owner_user_id,name) VALUES(1,1,1,'test team')"))
        await db.execute(text("INSERT INTO user_team_members(site_id,team_id,user_id,role) VALUES(1,1,1,'owner')"))
        await db.commit()
    monkeypatch.setattr(catalog, "debit_image_task_balance", AsyncMock(return_value=None))
    monkeypatch.setattr(catalog, "refund_image_task_balance", AsyncMock(return_value=None))
    monkeypatch.setattr(catalog, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()
    async with bootstrap.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    await bootstrap.dispose()


async def create(sessions, value, background=None, site_id=1):
    async with sessions() as db:
        user = await db.get(User, 1)
        if site_id != 1:
            user = SimpleNamespace(id=1, site_id=site_id, is_internal=False)
        return await catalog.create_batch_image_tasks(value, background if background is not None else BackgroundTasks(), user, db)


async def counts(sessions):
    async with sessions() as db:
        account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == 1))
        return (await db.scalar(select(func.count()).select_from(catalog.image_tasks_table)),
                await db.scalar(select(func.count()).select_from(CreditLedger)), account.balance, account.gift_balance)


async def test_groups_persist_all_reference_urls_and_bill_outputs_not_references(sessions):
    background = BackgroundTasks()
    result = await create(sessions, payload(), background)
    assert result.data["task_count"] == 3
    a_tasks = [task for task in result.data["tasks"] if task["input_group_id"] == "group-A"]
    assert len(a_tasks) == 2
    assert all(task["input_group_name"] == "商品A" and task["prompt"] == "白底\n保留细节" for task in a_tasks)
    assert all([asset["url"] for asset in task["input_images"]] == ["https://cdn.test/2.png", "https://cdn.test/1.png"] for task in a_tasks)
    assert await counts(sessions) == (3, 3, 1979, 0)
    jobs = background.tasks[0].args[0]
    assert jobs[0]["input_image_urls"] == ["https://cdn.test/2.png", "https://cdn.test/1.png"]
    # Reload through fresh sessions, as happens after API/worker restarts.
    async with sessions() as db:
        rows = (await db.execute(select(catalog.image_tasks_table).order_by(catalog.image_tasks_table.c.id))).mappings().all()
        assert [row["input_group_name"] for row in rows] == ["商品A", "商品A", "商品B"]
        assert rows[0]["input_group_path"] == "素材/商品A"
        assert json.loads(rows[0]["input_image_urls"]) == jobs[0]["input_image_urls"]


async def test_same_batch_concurrent_retries_only_debit_once_and_changed_payload_conflicts(sessions):
    value = payload()
    results = await asyncio.gather(*(create(sessions, value) for _ in range(5)))
    assert all(set(result.data["task_ids"]) == set(results[0].data["task_ids"]) for result in results)
    assert await counts(sessions) == (3, 3, 1979, 0)
    value["groups"][0]["prompt"] = "different"
    with pytest.raises(BusinessError) as caught:
        await create(sessions, value)
    assert caught.value.code == 40943
    assert await counts(sessions) == (3, 3, 1979, 0)


@pytest.mark.parametrize("work_type", ["batch_generate", "batch_edit"])
async def test_ordinary_batch_lost_response_and_concurrent_retries_bill_once(sessions, work_type):
    value = {"work_type": work_type, "model_id": 5, "batch_id": "batch-" + uuid4().hex,
             "prompt": "one\ntwo\nthree" if work_type == "batch_generate" else "white background",
             "input_image_ids": [] if work_type == "batch_generate" else [1, 2, 3],
             "resolution": "1k", "aspect_ratio": "1:1", "quality": "auto", "output_count": 1}
    if work_type == "batch_generate":
        async with sessions() as db:
            await db.execute(text("UPDATE image_models SET work_type='text_to_image' WHERE id=5"))
            await db.execute(text("UPDATE image_model_prices SET work_type='text_to_image' WHERE model_id=5"))
            await db.commit()
    results = await asyncio.gather(*(create(sessions, value) for _ in range(5)))
    assert all(set(result.data["task_ids"]) == set(results[0].data["task_ids"]) for result in results)
    assert await counts(sessions) == (3, 3, 1979, 0)
    background = BackgroundTasks()
    recovered = await create(sessions, value, background)
    assert set(recovered.data["task_ids"]) == set(results[0].data["task_ids"])
    assert background.tasks == []
    value["prompt"] += " changed"
    with pytest.raises(BusinessError) as caught:
        await create(sessions, value)
    assert caught.value.code == 40943
    assert await counts(sessions) == (3, 3, 1979, 0)


@pytest.mark.parametrize("asset_id", [4, 5, 9999])
async def test_unowned_cross_site_and_missing_images_reject_whole_batch_without_debit(sessions, asset_id):
    value = payload(); value["groups"][1]["input_image_ids"] = [asset_id]
    with pytest.raises(BusinessError) as caught: await create(sessions, value)
    assert caught.value.code == 40420
    assert await counts(sessions) == (0, 0, 2000, 20)


@pytest.mark.parametrize("change", ["missing-prompt", "duplicate-group", "too-many-refs", "invalid-count", "over-2000", "wrong-model"])
async def test_invalid_group_batches_never_create_or_debit(sessions, change):
    value = payload()
    if change == "missing-prompt": value["groups"][1]["prompt"] = " "
    elif change == "duplicate-group": value["groups"][1]["group_id"] = "group-A"
    elif change == "too-many-refs": value["groups"][0]["input_image_ids"] = [1, 2, 3]
    elif change == "invalid-count": value["groups"][0]["output_count"] = 1.5
    elif change == "over-2000": value["groups"] = [{**value["groups"][0], "group_id": f"group-{i}", "output_count": 9} for i in range(223)]
    elif change == "wrong-model": value["model_id"] = 999
    with pytest.raises(BusinessError): await create(sessions, value)
    assert await counts(sessions) == (0, 0, 2000, 20)


async def test_insufficient_credits_roll_back_prior_tasks_and_debits(sessions):
    async with sessions() as db:
        await db.execute(update(UserCreditAccount).where(UserCreditAccount.user_id == 1).values(balance=10, gift_balance=10)); await db.commit()
    with pytest.raises(BusinessError) as caught: await create(sessions, payload())
    assert caught.value.code == 40030
    assert await counts(sessions) == (0, 0, 10, 10)


async def test_single_task_failure_refunds_only_its_output_and_is_idempotent(sessions):
    result = await create(sessions, payload())
    task = result.data["tasks"][0]
    async with sessions() as db:
        await catalog.refund_image_task_credits(db, 1, task["task_no"], 7); await db.commit()
        await catalog.refund_image_task_credits(db, 1, task["task_no"], 7); await db.commit()
    assert await counts(sessions) == (3, 4, 1986, 6)


async def test_grouped_exports_use_ids_and_names_even_when_groups_share_first_reference(sessions, monkeypatch):
    value = payload(); value["groups"][1]["input_image_ids"] = [2, 3]
    result = await create(sessions, value)
    async with sessions() as db:
        await db.execute(update(catalog.image_tasks_table).values(status="succeeded", output_image_url="https://cdn.test/result.png")); await db.commit()
        user = await db.get(User, 1)
        items = await catalog._get_export_items(result.data["task_ids"], "", user, db)
    assert [item.group_name for item in items] == ["商品A", "商品A", "商品B"]
    monkeypatch.setattr(catalog_exports, "read_export_image", lambda url: (b"PNG-result", "image/png"))
    with await catalog_exports.build_export_archive(items) as archive:
        with ZipFile(archive) as zipped:
            names = zipped.namelist()
            assert sum('/01-商品A/' in name for name in names) == 2
            assert sum('/02-商品B/' in name for name in names) == 1
            manifest = zipped.read("manifest.csv").decode("utf-8-sig")
            assert "原任务组名称" in manifest and "group-A" in manifest and "group-B" in manifest


async def test_api_response_contract_returns_all_1000_grouped_outputs(sessions, monkeypatch):
    value = payload(); value["groups"] = [{**value["groups"][1], "group_id": f"group-{i}", "group_name": f"商品{i}"} for i in range(1000)]
    async with sessions() as db:
        await db.execute(update(UserCreditAccount).where(UserCreditAccount.user_id == 1).values(balance=10000)); await db.commit()
    monkeypatch.setattr(catalog, "execute_image_task_batch", AsyncMock())
    async def db_override():
        async with sessions() as db: yield db
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, site_id=1, nickname="", username="test", active_team_id=1, is_internal=False)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/image-tasks/batch", json=value)
        assert response.status_code == 200, response.text
        assert len(response.json()["data"]["tasks"]) == 1000
        assert await counts(sessions) == (1000, 1000, 3000, 0)
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(previous)


@pytest.mark.parametrize("mode,expected", [("shared", 2), ("per_image", 2), ("matrix", 4)])
async def test_existing_batch_modes_remain_compatible(sessions, mode, expected):
    value = payload(); value.update(prompt_mode=mode, prompt="白底\n客厅" if mode != "shared" else "统一白底", input_image_ids=[1, 2]); value.pop("groups")
    result = await create(sessions, value)
    assert result.data["task_count"] == expected
    assert all(task["input_group_id"] == "" and len(task["input_images"]) == 1 for task in result.data["tasks"])


def test_group_validator_rejects_coerced_ids_and_counts():
    for invalid in [True, "1", 1.5, 0, -1]:
        value = payload()["groups"]; value[0]["input_image_ids"] = [invalid]
        with pytest.raises(BusinessError): validate_batch_groups(value, 8)
    for invalid in [True, "2", 0, 10]:
        value = payload()["groups"]; value[0]["output_count"] = invalid
        with pytest.raises(BusinessError): validate_batch_groups(value, 8)


async def test_worker_receives_all_group_references_and_failure_preserves_other_outputs(sessions, monkeypatch):
    from app.services.image_generation import GeneratedImage, GenerationModelConfig
    value = payload()
    result = await create(sessions, value)
    async with sessions() as db:
        await db.execute(text("SELECT setval(pg_get_serial_sequence('public.image_assets','id'),100000,false)")); await db.commit()
    config = GenerationModelConfig(provider_code="test", provider_name="test", base_url="https://provider.invalid", access_mode="api", api_key="test-only", auth_type="bearer", timeout_seconds=120, vendor_model="test", disable_retry=True)
    monkeypatch.setattr(catalog, "generation_model_config", AsyncMock(return_value=config))
    calls = []
    async def provider(_config, prompt, inputs, *args, **kwargs):
        calls.append((prompt, inputs))
        if prompt == "客厅场景": raise BusinessError("test provider failure", code=50214, status_code=502)
        return GeneratedImage(content=b"test-output", mime_type="image/png"), {}
    monkeypatch.setattr(catalog, "run_image_generation_in_executor", provider)
    async def storage(**kwargs):
        return {"storage_key": "result/"+uuid4().hex+".png", "url": "https://cdn.test/output.png", "mime_type": "image/png", "width": 1, "height": 1, "size_bytes": 11, "sha256": "a"*64}
    monkeypatch.setattr(catalog, "run_generated_image_storage_in_executor", storage)
    # Run through the real worker's state transitions, asset insert and refunds.
    for task in reversed(result.data["tasks"]):
        async with sessions() as db:
            status, output = await catalog.execute_image_task(db, task["id"], 1, 1, 5, task["prompt"], 7, task["task_no"], input_image_url=task["input_images"][0]["url"], input_image_urls=[asset["url"] for asset in task["input_images"]], resolution="1k", aspect_ratio="1:1")
            assert status == ("failed" if task["input_group_id"] == "group-B" else "succeeded")
    assert calls == [("白底\n保留细节", ["https://cdn.test/2.png", "https://cdn.test/1.png"])]*2 + [("客厅场景", ["https://cdn.test/3.png"])]
    assert await counts(sessions) == (3, 4, 1986, 6)
    async with sessions() as db:
        rows = (await db.execute(select(catalog.image_tasks_table).order_by(catalog.image_tasks_table.c.id))).mappings().all()
        assert [row["status"] for row in rows] == ["succeeded", "succeeded", "failed"]
        assert [row["input_group_name"] for row in rows] == ["商品A", "商品A", "商品B"]
        assert await db.scalar(select(func.count()).select_from(ImageAsset).where(ImageAsset.source == "generated")) == 2


async def test_group_migration_round_trip_retains_legacy_tasks(sessions):
    legacy = payload(); legacy.update(prompt_mode="shared", prompt="legacy", input_image_ids=[1]); legacy.pop("groups")
    await create(sessions, legacy)
    spec = importlib.util.spec_from_file_location("group_migration", Path(__file__).parents[1]/"alembic/versions/20261006_0100_image_task_input_groups.py")
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    async with sessions() as db:
        connection = await db.connection()
        def round_trip(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade(); migration.upgrade()
        await connection.run_sync(round_trip)
        await db.commit()
    async with sessions() as db:
        rows = (await db.execute(select(catalog.image_tasks_table))).mappings().all()
        assert len(rows) == 1 and rows[0]["prompt"] == "legacy" and rows[0]["input_group_id"] is None
