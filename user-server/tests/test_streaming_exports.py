import asyncio
import csv
import threading
from io import BytesIO, StringIO
from zipfile import ZipFile
from types import SimpleNamespace
from unittest.mock import AsyncMock

from anyio import CapacityLimiter

from app.api.routes import catalog_exports as exports
from app.api.routes import catalog
from app.core.exceptions import BusinessError


async def collect(stream, prefix=b""):
    return prefix + b"".join([chunk async for chunk in stream])


async def wait_event(event):
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.01)


async def test_browser_receives_zip_before_slow_images_finish_and_archive_is_valid(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def read(url):
        started.set()
        assert release.wait(3)
        return url.encode(), "image/png"

    monkeypatch.setattr(exports, "read_export_image", read)
    stream = exports.stream_export_archive([
        exports.ExportItem(f"IMG-{i}", f"https://cdn.test/{i}.png", prompt="白底", batch_id="batch", group_id=str(i), group_name=f"商品{i}")
        for i in range(200)
    ])
    prefix = await anext(stream)
    assert prefix == b"PK\x03\x04"
    consumer = asyncio.create_task(collect(stream, prefix))
    try:
        await wait_event(started)
        assert not consumer.done(), "browser already has ZIP header while reads are blocked"
    finally:
        release.set()
    archive_bytes = await asyncio.wait_for(consumer, 5)
    with ZipFile(BytesIO(archive_bytes)) as archive:
        assert archive.testzip() is None
        images = [name for name in archive.namelist() if name.endswith(".png")]
        assert len(images) == 200
        assert archive.read(images[0]) == b"https://cdn.test/0.png"
        rows = list(csv.DictReader(StringIO(archive.read("manifest.csv").decode("utf-8-sig"))))
        assert len(rows) == 200 and all(row["状态"] == "成功" for row in rows)
        assert len({row["商品组"] for row in rows}) == 200


async def test_failed_files_and_size_limit_leave_valid_zip_with_honest_manifest(monkeypatch):
    monkeypatch.setattr(exports.settings, "image_export_max_bytes", 3)

    def read(url):
        if url == "bad":
            raise BusinessError("原图不可用", code=50220)
        return b"ok", "image/png"

    monkeypatch.setattr(exports, "read_export_image", read)
    data = await collect(exports.stream_export_archive([(str(i), url) for i, url in enumerate(["good", "bad", "over", "later"])]))
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert len([name for name in archive.namelist() if name.endswith(".png")]) == 1
        rows = list(csv.DictReader(StringIO(archive.read("manifest.csv").decode("utf-8-sig"))))
        assert [row["状态"] for row in rows] == ["成功", "失败", "失败", "失败"]
        assert "原图不可用" in rows[1]["错误"]
        assert "大小" in rows[2]["错误"]


async def test_all_cdn_failures_are_recorded_without_corrupting_download(monkeypatch):
    def read(url):
        raise BusinessError("无法获取结果图片", code=50220)

    monkeypatch.setattr(exports, "read_export_image", read)
    data = await collect(exports.stream_export_archive([("IMG", "bad")]))
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert "失败" in archive.read("manifest.csv").decode("utf-8-sig")


async def test_prefetch_is_bounded_and_queued_exports_still_send_first_bytes(monkeypatch):
    monkeypatch.setattr(exports, "export_limiter", CapacityLimiter(1))
    monkeypatch.setattr(exports.settings, "image_export_download_workers", 3)
    lock, started, release, second_started = threading.Lock(), threading.Event(), threading.Event(), threading.Event()
    active = 0
    peak = 0

    def read(url):
        nonlocal active, peak
        if url == "second":
            second_started.set()
            return b"ok", "image/png"
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 3:
                started.set()
        try:
            assert release.wait(3)
            return b"x" * 100000, "image/png"
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(exports, "read_export_image", read)
    first = exports.stream_export_archive([(str(i), str(i)) for i in range(20)])
    prefix = await anext(first)
    first_download = asyncio.create_task(collect(first, prefix))
    second = exports.stream_export_archive([("second", "second")])
    second_prefix = await anext(second)
    assert second_prefix == prefix
    second_download = asyncio.create_task(collect(second, second_prefix))
    try:
        await wait_event(started)
        assert not second_started.is_set(), "queued stream registers download without exceeding export slots"
        assert peak == 3
    finally:
        release.set()
    one, two = await asyncio.wait_for(asyncio.gather(first_download, second_download), 5)
    assert peak <= 3 and second_started.is_set()
    assert ZipFile(BytesIO(one)).testzip() is None
    assert ZipFile(BytesIO(two)).testzip() is None


async def test_disconnect_stops_full_queue_and_releases_export_slot(monkeypatch):
    limiter = CapacityLimiter(1)
    monkeypatch.setattr(exports, "export_limiter", limiter)
    monkeypatch.setattr(exports, "read_export_image", lambda url: (b"x" * 2000000, "image/png"))
    stream = exports.stream_export_archive([("IMG", "https://cdn.test/image.png")])
    assert await anext(stream) == b"PK\x03\x04"
    await asyncio.sleep(0.15)
    assert limiter.borrowed_tokens == 1
    await asyncio.wait_for(stream.aclose(), 3)
    assert limiter.borrowed_tokens == 0
    assert ZipFile(BytesIO(await collect(exports.stream_export_archive([("IMG2", "next")])))).testzip() is None


async def test_download_route_sends_headers_and_body_before_cdn_and_releases_database(monkeypatch):
    db = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(is_active=True)), rollback=AsyncMock())
    monkeypatch.setattr(catalog, "verify_export_access_token", lambda token: {"sub":"1", "batch_id":"batch"})
    monkeypatch.setattr(catalog, "_get_export_items", AsyncMock(return_value=[exports.ExportItem("IMG", "https://cdn.test/result.png")]))
    started, release, first_body = threading.Event(), threading.Event(), asyncio.Event()
    messages = []

    def read(url):
        assert db.rollback.await_count == 1
        started.set()
        assert release.wait(3)
        return b"image", "image/png"

    monkeypatch.setattr(exports, "read_export_image", read)
    response = await catalog.download_image_tasks_export(ticket="signed-ticket", db=db)
    assert not started.is_set(), "returning the response never waits for CDN or ZIP work"

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            first_body.set()

    download = asyncio.create_task(response({"type":"http", "asgi":{"spec_version":"2.4"}}, None, send))
    try:
        await asyncio.wait_for(first_body.wait(), 1)
        await wait_event(started)
        assert not download.done()
        headers = dict(messages[0]["headers"])
        assert messages[0]["status"] == 200
        assert headers[b"content-disposition"].startswith(b"attachment;")
        assert headers[b"x-accel-buffering"] == b"no"
        assert headers[b"cache-control"] == b"no-store"
        assert messages[1]["body"] == b"PK\x03\x04"
    finally:
        release.set()
    await asyncio.wait_for(download, 5)
    data = b"".join(message.get("body", b"") for message in messages)
    assert ZipFile(BytesIO(data)).testzip() is None
