"""Exercise history pagination against PostgreSQL with isolated test schemas."""
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.api.routes import catalog
from app.db.session import get_db
from app.main import app


EDIT_TYPES = ["image_edit", "image_to_image", "batch_edit"]


@pytest.fixture
async def history(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    schema = "task_history_" + uuid4().hex
    bootstrap = create_async_engine(url)
    async with bootstrap.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        for table in ("image_tasks", "image_models", "users"):
            await conn.execute(text(f"CREATE TABLE {schema}.{table} (LIKE public.{table} INCLUDING ALL)"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    def record(task_id, **values):
        return dict(id=task_id, task_no=f"HISTORY-{task_id}", user_id=1, site_id=1,
                    model_id=5, work_type="image_edit", prompt="history test", status="succeeded",
                    created_at=now, timeout_seconds=180, batch_id="history", team_id=None,
                    deleted_at=None, **values)

    rows = []
    for task_id in range(1, 221):
        row = record(task_id)
        row["work_type"] = EDIT_TYPES[(task_id - 1) % 3] if task_id <= 120 else "text_to_image"
        rows.append(row)
    rows[118].update(status="refunded", work_type="image_edit")
    rows[119].update(status="failed", work_type="image_edit")
    for task_id, changes in (
        (221, dict(site_id=2, team_id=7)),
        (222, dict(user_id=2, team_id=7)),
        (223, dict(deleted_at=now)),
        (224, dict(created_at=now - timedelta(days=8))),
        (225, dict(user_id=2, team_id=8)),
    ):
        row = record(task_id)
        row.update(changes)
        rows.append(row)

    monkeypatch.setattr(catalog, "image_history_is_shared", AsyncMock(return_value=False))
    monkeypatch.setattr(catalog, "get_primary_team_id", AsyncMock(return_value=7))
    previous = app.dependency_overrides.copy()

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, site_id=1)
    try:
        async with sessions() as db:
            await db.execute(catalog.image_tasks_table.insert(), rows)
            await db.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, sessions, record
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        await engine.dispose()
        async with bootstrap.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await bootstrap.dispose()


def edit_params(**extra):
    return [("work_types", value) for value in EDIT_TYPES] + list(extra.items())


async def test_edit_history_crosses_80_without_text_tasks_gaps_or_duplicates(history):
    client, sessions, record = history
    ids = []
    cursor = None
    for page in range(4):
        params = edit_params(limit=40)
        if cursor is not None:
            params.append(("before_id", cursor))
        response = await client.get("/image-tasks", params=params)
        assert response.status_code == 200, response.text
        items = response.json()["data"]
        assert len(items) == (40 if page < 3 else 0)
        assert all(item["work_type"] in EDIT_TYPES for item in items)
        ids.extend(item["id"] for item in items)
        if items:
            cursor = min(item["id"] for item in items)
        if page == 0:
            # A new task arrives while the user is paging through older tasks.
            async with sessions() as db:
                await db.execute(catalog.image_tasks_table.insert().values(**record(1000)))
                await db.commit()
    assert ids == list(range(120, 0, -1))


async def test_unfiltered_history_keeps_existing_default_contract(history):
    response = await history[0].get("/image-tasks")
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) == 80
    assert items[0]["id"] == 220
    assert {item["work_type"] for item in items} == {"text_to_image"}


async def test_history_filters_combine_with_batch_status_and_cursor(history):
    response = await history[0].get("/image-tasks", params=edit_params(
        limit=40, before_id=121, batch_id="history", status="failed",
    ))
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [120, 119]
    response = await history[0].get("/image-tasks", params={"work_types": "image_to_image", "limit": 200})
    assert response.status_code == 200
    assert response.json()["data"]
    assert all(item["work_type"] == "image_to_image" for item in response.json()["data"])


async def test_shared_history_respects_site_team_deletion_and_retention(history, monkeypatch):
    monkeypatch.setattr(catalog, "image_history_is_shared", AsyncMock(return_value=True))
    response = await history[0].get("/image-tasks", params=edit_params(limit=200))
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [222, *range(120, 0, -1)]


@pytest.mark.parametrize("params", [
    {"limit": 201}, {"limit": 0}, {"before_id": 0},
    [("work_types", "image_edit")] * 21,
])
async def test_history_query_bounds_are_enforced(history, params):
    response = await history[0].get("/image-tasks", params=params)
    assert response.status_code == 422
