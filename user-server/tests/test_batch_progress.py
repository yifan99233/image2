from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, update

from app.api.deps import get_current_user
from app.api.routes import catalog, catalog_exports
from app.db.session import get_db
from app.main import app
from app.models.user import User
from test_batch_groups import sessions  # isolated real PostgreSQL schema


async def seed(sessions, batch_id, statuses, **overrides):
    now = datetime.now(UTC)
    rows = [{"task_no": f"{batch_id}-{i}-{overrides.get('user_id', 1)}-{overrides.get('site_id', 1)}",
             "batch_id": batch_id, "user_id": 1, "site_id": 1, "team_id": 1,
             "model_id": 5, "work_type": "batch_generate", "prompt": f"prompt-{i}",
             "status": status, "timeout_seconds": 180,
             "created_at": now, "deleted_at": None,
             "output_image_url": f"https://cdn.test/{batch_id}/{i}.png" if status == "succeeded" else None,
             "failure_message": "上游失败" if status in ("failed", "refunded") else None,
             **overrides} for i, status in enumerate(statuses)]
    async with sessions() as db:
        await db.execute(catalog.image_tasks_table.insert(), rows)
        await db.commit()


@pytest.fixture
async def batch_client(sessions):
    async def database():
        async with sessions() as db:
            yield db
    async def user():
        async with sessions() as db:
            return await db.get(User, 1)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


async def test_complete_2000_task_summary_visibility_and_live_statuses(sessions, batch_client):
    await seed(sessions, "large", ["succeeded"] * 1700 + ["failed"] * 80 + ["refunded"] * 20 + ["queued"] * 180 + ["running"] * 15 + ["pending"] * 5)
    await seed(sessions, "large", ["succeeded"] * 4, user_id=2)
    await seed(sessions, "large", ["succeeded"] * 3, site_id=2)
    await seed(sessions, "deleted", ["succeeded"] * 2, deleted_at=datetime.now(UTC))
    await seed(sessions, "other", ["failed"], user_id=2)
    response = await batch_client.get("/image-tasks/batches?work_type=batch_generate")
    assert response.status_code == 200
    page = response.json()["data"]
    assert len(page["items"]) == 1 and not page["has_more"]
    summary = page["items"][0]
    assert {key: summary[key] for key in ("task_count", "pending_count", "queued_count", "running_count", "succeeded_count", "failed_count", "downloadable_count")} == {
        "task_count": 2000, "pending_count": 5, "queued_count": 180, "running_count": 15,
        "succeeded_count": 1700, "failed_count": 100, "downloadable_count": 1700}
    async with sessions() as db:
        await db.execute(update(catalog.image_tasks_table).where(catalog.image_tasks_table.c.user_id == 1, catalog.image_tasks_table.c.site_id == 1, catalog.image_tasks_table.c.batch_id == "large", catalog.image_tasks_table.c.status.in_(("pending", "queued", "running"))).values(status="failed"))
        await db.commit()
    response = await batch_client.post("/image-tasks/batches/statuses", json={"batch_ids": ["large", "large", "other", "missing"]})
    summaries = response.json()["data"]
    assert len(summaries) == 1 and summaries[0]["failed_count"] == 300
    assert summaries[0]["pending_count"] + summaries[0]["queued_count"] + summaries[0]["running_count"] == 0


async def test_batch_pages_do_not_repeat_and_only_count_last_seven_days(sessions, batch_client):
    await seed(sessions, "old-only", ["queued"], created_at=datetime.now(UTC) - timedelta(days=8))
    await seed(sessions, "boundary", ["succeeded"], created_at=datetime.now(UTC) - timedelta(days=8))
    await seed(sessions, "boundary", ["running"], user_id=1, site_id=1, task_no="boundary-new")
    await seed(sessions, "edit", ["succeeded"], work_type="batch_edit")
    for i in range(12):
        await seed(sessions, f"page-{i}", ["succeeded"])
    ids = []
    cursor = None
    while True:
        response = await batch_client.get("/image-tasks/batches", params={"work_type": "batch_generate", "limit": 5, **({"before_id": cursor} if cursor else {})})
        assert response.status_code == 200
        page = response.json()["data"]
        ids.extend(item["batch_id"] for item in page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(ids) == len(set(ids)) == 13 and "old-only" not in ids and "edit" not in ids
    summary = (await batch_client.post("/image-tasks/batches/statuses", json={"batch_ids": ["boundary"]})).json()["data"][0]
    assert summary["task_count"] == 1 and summary["running_count"] == 1 and summary["succeeded_count"] == 0
    edit = (await batch_client.get("/image-tasks/batches?work_type=batch_edit")).json()["data"]
    assert [item["batch_id"] for item in edit["items"]] == ["edit"]


async def test_failure_filter_and_cursor_include_refunds_only_for_visible_batch(sessions, batch_client):
    await seed(sessions, "failures", ["failed"] * 20 + ["refunded"] * 5 + ["succeeded"] * 10)
    await seed(sessions, "failures", ["failed"] * 3, user_id=2)
    await seed(sessions, "wrong-batch", ["failed"] * 5)
    first = (await batch_client.get("/image-tasks", params={"batch_id": "failures", "status": "failed", "limit": 20})).json()["data"]
    second = (await batch_client.get("/image-tasks", params={"batch_id": "failures", "status": "failed", "limit": 20, "before_id": first[-1]["id"]})).json()["data"]
    assert len(first) == 20 and len(second) == 5
    assert len({task["id"] for task in first + second}) == 25
    assert {task["status"] for task in first + second} == {"failed", "refunded"}
    assert all(task["batch_id"] == "failures" and task["failure_message"] == "上游失败" for task in first + second)


async def test_entire_batch_export_ticket_downloads_200_images_not_loaded_cards(sessions, batch_client, monkeypatch):
    await seed(sessions, "download", ["succeeded"] * 200 + ["failed"] * 2)
    await seed(sessions, "download", ["succeeded"] * 3, user_id=2)
    await seed(sessions, "other-download", ["succeeded"] * 4)
    monkeypatch.setattr(catalog_exports, "read_export_image", lambda url: (url.encode(), "image/png"))
    ticket = await batch_client.post("/image-tasks/export-ticket", json={"task_ids": [], "batch_id": "download"})
    assert ticket.status_code == 200
    response = await batch_client.get(ticket.json()["data"]["download_url"])
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        images = [name for name in archive.namelist() if name.endswith(".png")]
        assert len(images) == 200
        assert all(archive.read(name).startswith(b"https://cdn.test/download/") for name in images)
        from test_prompt_exports import xlsx_rows
        assert len(xlsx_rows(archive.read("完整汇总.xlsx"))) == 203
        assert len(xlsx_rows(archive.read("失败汇总.xlsx"))) == 3
        assert archive.read("结果统计.txt").decode() == "成功 200 张，失败 2 张\n"


async def test_failed_only_batch_can_download_reports_without_reading_images(sessions, batch_client, monkeypatch):
    await seed(sessions, "failed-only", ["failed", "refunded"], input_group_name="【XMAS-SER-480】")
    def never_read(url):
        raise AssertionError("failed tasks have no image download")
    monkeypatch.setattr(catalog_exports, "read_export_image", never_read)
    ticket = await batch_client.post("/image-tasks/export-ticket", json={"batch_id": "failed-only"})
    assert ticket.status_code == 200
    response = await batch_client.get(ticket.json()["data"]["download_url"])
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"【XMAS-SER-480】/", "完整汇总.xlsx", "失败汇总.xlsx", "结果统计.txt"}
        assert archive.read("结果统计.txt").decode() == "成功 0 张，失败 2 张\n"


async def test_shared_team_summary_respects_entitlement_and_site(sessions, batch_client):
    await seed(sessions, "team", ["succeeded"], user_id=2)
    await seed(sessions, "team", ["failed"], site_id=2)
    assert (await batch_client.get("/image-tasks/batches?work_type=batch_generate")).json()["data"]["items"] == []
    async with sessions() as db:
        await db.execute(text("UPDATE user_teams SET image_history_shared=true WHERE id=1"))
        await db.execute(text("INSERT INTO team_entitlements(site_id,owner_user_id,seat_count,source,source_reference,status,starts_at) VALUES(1,1,2,'test','test','active',now())"))
        await db.commit()
    items = (await batch_client.get("/image-tasks/batches?work_type=batch_generate")).json()["data"]["items"]
    assert len(items) == 1 and items[0]["task_count"] == items[0]["succeeded_count"] == 1


@pytest.mark.parametrize("path", ["/image-tasks/batches?work_type=text_to_image", "/image-tasks/batches?work_type=batch_generate&limit=21", "/image-tasks/batches?work_type=batch_generate&before_id=0", "/image-tasks?status=invalid"])
async def test_invalid_batch_query_rejected(batch_client, path):
    assert (await batch_client.get(path)).status_code == 422


@pytest.mark.parametrize("ids", [[], ["a"] * 21])
async def test_status_poll_size_is_bounded(batch_client, ids):
    assert (await batch_client.post("/image-tasks/batches/statuses", json={"batch_ids": ids})).status_code == 422
