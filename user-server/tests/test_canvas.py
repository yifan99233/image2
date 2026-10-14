import asyncio
from uuid import uuid4

import pytest
from fastapi import Header
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.user import User


@pytest.fixture
async def canvas_client():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        users = [User(site_id=site, username=f"canvas-{uuid4().hex}", email=f"{uuid4().hex}@example.test", password_hash="unused") for site in (1, 1, 2)]
        db.add_all(users)
        await db.commit()

    async def user(x_test_user: int = Header(default=0)):
        return users[x_test_user]

    async def session():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_db] = session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def document(revision=0, title="测试画布"):
    return {"revision": revision, "mutation_id": uuid4().hex, "title": title,
            "document": {"nodes": [{"id": "text-1", "type": "text", "metadata": {"content": "hello"}}], "connections": []}}


async def test_canvas_persists_and_isolates_users_and_sites(canvas_client):
    client = canvas_client
    key = uuid4().hex
    saved = await client.put(f"/canvas/projects/{key}", json=document())
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["revision"] == 1
    for owner in (1, 2):
        headers = {"X-Test-User": str(owner)}
        assert (await client.get(f"/canvas/projects/{key}", headers=headers)).status_code == 404
        assert (await client.get("/canvas/projects", headers=headers)).json()["data"]["items"] == []
        assert (await client.delete(f"/canvas/projects/{key}?revision=1", headers=headers)).status_code == 200
    loaded = (await client.get(f"/canvas/projects/{key}")).json()["data"]
    assert loaded["document"]["nodes"][0]["metadata"]["content"] == "hello"


async def test_canvas_conflict_and_idempotent_retry(canvas_client):
    client = canvas_client
    key = uuid4().hex
    original = document()
    assert (await client.put(f"/canvas/projects/{key}", json=original)).status_code == 200
    assert (await client.put(f"/canvas/projects/{key}", json=original)).json()["data"]["revision"] == 1
    updated = document(1, "最新版本")
    assert (await client.put(f"/canvas/projects/{key}", json=updated)).json()["data"]["revision"] == 2
    assert (await client.put(f"/canvas/projects/{key}", json=updated)).json()["data"]["revision"] == 2
    assert (await client.put(f"/canvas/projects/{key}", json=document(1, "旧页面"))).status_code == 409
    assert (await client.delete(f"/canvas/projects/{key}?revision=1")).status_code == 409
    assert (await client.get(f"/canvas/projects/{key}")).json()["data"]["title"] == "最新版本"
    assert (await client.delete(f"/canvas/projects/{key}?revision=2")).status_code == 200
    assert (await client.get(f"/canvas/projects/{key}")).status_code == 404
    assert (await client.put(f"/canvas/projects/{key}", json=original)).status_code == 409
    assert (await client.put(f"/canvas/projects/{key}", json=document(2))).status_code == 409


async def test_canvas_bounded_pagination_and_validation(canvas_client):
    client = canvas_client
    ids = [uuid4().hex for _ in range(3)]
    for key in ids:
        assert (await client.put(f"/canvas/projects/{key}", json=document())).status_code == 200
    first = (await client.get("/canvas/projects?limit=2")).json()["data"]
    assert first["has_more"] is True
    assert len(first["items"]) == 2
    assert "document" not in first["items"][0]
    tail = first["items"][-1]
    second = (await client.get("/canvas/projects", params={"limit": 2, "before_created_at": tail["created_at"], "before_id": tail["id"]})).json()["data"]
    assert second["has_more"] is False
    assert {item["id"] for item in first["items"] + second["items"]} == set(ids)
    assert (await client.get("/canvas/projects?limit=101")).status_code == 422
    invalid = document()
    invalid["document"]["nodes"][0]["metadata"]["content"] = "blob:browser-only-image"
    assert (await client.put(f"/canvas/projects/{uuid4().hex}", json=invalid)).status_code == 422
    invalid = document()
    invalid["document"]["nodes"].append(invalid["document"]["nodes"][0])
    assert (await client.put(f"/canvas/projects/{uuid4().hex}", json=invalid)).status_code == 422


async def test_canvas_requires_authentication(client):
    assert (await client.get("/canvas/projects")).status_code == 401


async def test_canvas_concurrent_writers_do_not_lose_changes(canvas_client):
    key = uuid4().hex
    await canvas_client.put(f"/canvas/projects/{key}", json=document())
    responses = await asyncio.gather(*[
        canvas_client.put(f"/canvas/projects/{key}", json=document(1, title))
        for title in ("页面 A", "页面 B")
    ])
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json()["data"] for response in responses if response.status_code == 200)
    stored = (await canvas_client.get(f"/canvas/projects/{key}")).json()["data"]
    assert stored["revision"] == 2
    assert stored["title"] == winner["title"]
