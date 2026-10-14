import asyncio
import threading
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from anyio import CapacityLimiter
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.api.routes import catalog, catalog_exports
from app.db.session import get_db
from app.main import app


def test_export_archive_preserves_names_and_contents(monkeypatch):
    monkeypatch.setattr(catalog_exports, "read_export_image", lambda url: (url.encode(), "image/jpeg"))
    with catalog_exports._build_export_archive([("IMG1", "https://cdn/1"), ("IMG2", "https://cdn/2")]) as archive:
        with ZipFile(archive) as result:
            assert result.namelist() == ["001-IMG1.jpg", "002-IMG2.jpg"]
            assert result.read("002-IMG2.jpg") == b"https://cdn/2"


def test_export_archive_skips_missing_images_and_keeps_manifest(monkeypatch):
    def read_image(url):
        if url.endswith("/missing"):
            raise catalog_exports.BusinessError("图片不存在", code=50220, status_code=502)
        return b"valid-image", "image/png"

    monkeypatch.setattr(catalog_exports, "read_export_image", read_image)
    with catalog_exports._build_export_archive(
        [
            catalog_exports.ExportItem("IMG1", "https://cdn/valid", batch_id="batch-test"),
            catalog_exports.ExportItem("IMG2", "https://cdn/missing", batch_id="batch-test"),
        ]
    ) as archive:
        with ZipFile(archive) as result:
            assert result.read("batch-test/生成结果/001-result-IMG1.png") == b"valid-image"
            assert "manifest.csv" in result.namelist()
            assert "IMG2" in result.read("manifest.csv").decode("utf-8-sig")


@pytest.mark.asyncio
async def test_slow_export_releases_database_and_does_not_block_login_key(monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [
            SimpleNamespace(task_no="IMG1", output_image_url="https://cdn/result.png"),
        ])),
        rollback=AsyncMock(),
    )

    def slow_download(url):
        assert db.rollback.await_count == 1
        started.set()
        release.wait(2)
        finished.set()
        return b"test-image", "image/png"

    monkeypatch.setattr(catalog_exports, "read_export_image", slow_download)
    monkeypatch.setattr(catalog_exports, "export_limiter", CapacityLimiter(1))
    monkeypatch.setattr(catalog, "visible_task_condition", AsyncMock(return_value=True))
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, site_id=1)
    app.dependency_overrides[get_db] = lambda: db
    export = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            export = asyncio.create_task(client.post("/image-tasks/export", json={"task_ids": [1]}))
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            key = await asyncio.wait_for(client.get("/auth/public-key"), timeout=0.5)
            assert key.status_code == 200
            assert not finished.is_set(), "Login key must return while the image download is still blocked"
            release.set()
            response = await export
            assert response.status_code == 200
            with ZipFile(BytesIO(response.content)) as result:
                assert result.read("batch/生成结果/001-result-IMG1.png") == b"test-image"
    finally:
        release.set()
        if export is not None:
            await export
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)


@pytest.mark.asyncio
async def test_export_worker_concurrency_is_bounded(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_download(url):
        calls.append(url)
        started.set()
        release.wait(2)
        return b"image", "image/png"

    monkeypatch.setattr(catalog_exports, "read_export_image", slow_download)
    monkeypatch.setattr(catalog_exports, "export_limiter", CapacityLimiter(1))
    first = asyncio.create_task(catalog_exports.build_export_archive([("IMG1", "first")]))
    second = asyncio.create_task(catalog_exports.build_export_archive([("IMG2", "second")]))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        await asyncio.sleep(0.05)
        assert calls == ["first"]
    finally:
        release.set()
        for archive in await asyncio.gather(first, second):
            archive.close()
    assert calls == ["first", "second"]
