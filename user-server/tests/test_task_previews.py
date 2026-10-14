import os
from io import BytesIO
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import catalog
from app.api.routes.catalog_serializers import serialize_task
from app.db.session import get_db
from app.main import app
from app.services.image_thumbnails import create_webp_thumbnail, thumbnail_path

SOURCE = "https://magic.shyfai.com/image2-assets/generated/example.png"
INPUTS = ["https://magic.shyfai.com/image2-assets/images/one.png", "https://magic.shyfai.cn/image2-assets/images/two.png"]


@pytest.fixture
async def previews(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    schema = "task_previews_" + uuid4().hex
    bootstrap = create_async_engine(url)
    async with bootstrap.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        await conn.execute(text(f"CREATE TABLE {schema}.image_tasks (LIKE public.image_tasks INCLUDING ALL)"))
    engine = create_async_engine(url, pool_size=3, max_overflow=0, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    original = BytesIO()
    Image.new("RGB", (1800, 1200), "navy").save(original, format="PNG")
    webp = create_webp_thumbnail(original.getvalue())
    import json
    try:
        async with sessions() as db:
            await db.execute(text("INSERT INTO image_tasks(id,task_no,user_id,site_id,model_id,work_type,prompt,status,output_image_url,input_image_url,input_image_urls,timeout_seconds) VALUES(7,'IMG-PREVIEW',1,1,5,'image_edit','test','succeeded',:output,:input,:inputs,180)"), {"output": SOURCE, "input": INPUTS[0], "inputs": json.dumps(INPUTS)})
            await db.execute(text("INSERT INTO image_tasks(id,task_no,user_id,site_id,model_id,work_type,prompt,status,input_image_url,timeout_seconds) VALUES(8,'IMG-LEGACY',1,1,5,'image_edit','test','running',:input,180)"), {"input": INPUTS[0]})
            await db.commit()
        reads = []
        def thumbnail(task_id, source_url):
            assert engine.sync_engine.pool.checkedout() == 0, "thumbnail work retains a database connection"
            reads.append((task_id, source_url))
            return webp
        monkeypatch.setattr(catalog, "get_or_create_thumbnail", thumbnail)
        async def database():
            async with sessions() as db:
                yield db
        previous = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = database
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                yield client, reads, webp, sessions, engine
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
    finally:
        await engine.dispose()
        async with bootstrap.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await bootstrap.dispose()


def test_task_exposes_input_previews_in_order_without_replacing_originals():
    import json
    task = serialize_task({"id": 7, "input_image_urls": json.dumps(INPUTS), "output_image_url": SOURCE, "status": "succeeded"})
    for index, asset in enumerate(task["input_images"]):
        assert asset["url"] == INPUTS[index].replace("magic.shyfai.com/", "magic.shyfai.cn/")
        assert asset["thumbnail_url"] == thumbnail_path(7, asset["url"], input_index=index)
    assert task["output_images"][0]["url"].endswith("/example.png")
    assert "input_index" not in task["output_images"][0]["thumbnail_url"]


@pytest.mark.parametrize("source,index", [(SOURCE,None), (SOURCE.replace(".com/", ".cn/"),None), (INPUTS[0].replace(".com/", ".cn/"),0), (INPUTS[0],0), (INPUTS[1],1)])
async def test_thumbnail_is_bound_to_asset_handles_domain_aliases_and_releases_db(previews, source, index):
    client, reads, webp, *_ = previews
    response = await client.get(thumbnail_path(7, source, input_index=index))
    assert response.status_code == 200, response.text
    assert response.content == webp
    assert response.headers["content-type"] == "image/webp"
    assert "immutable" in response.headers["cache-control"]
    assert reads == [(7, SOURCE if index is None else INPUTS[index])]


@pytest.mark.parametrize("path", [thumbnail_path(7, SOURCE, input_index=0), thumbnail_path(7, INPUTS[0], input_index=1), thumbnail_path(7, INPUTS[1], input_index=20), thumbnail_path(99, SOURCE), "/image-tasks/7/thumbnail?token=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", thumbnail_path(8, INPUTS[0])])
async def test_invalid_or_swapped_capabilities_do_not_read_any_image(previews, path):
    response = await previews[0].get(path)
    assert response.status_code == 404
    assert previews[1] == []


async def test_legacy_single_input_can_be_previewed_before_task_finishes(previews):
    response = await previews[0].get(thumbnail_path(8, INPUTS[0], input_index=0))
    assert response.status_code == 200
    assert previews[1] == [(8, INPUTS[0])]


async def test_negative_input_index_is_rejected(previews):
    response = await previews[0].get(thumbnail_path(7, INPUTS[0], input_index=-1))
    assert response.status_code == 422
    assert previews[1] == []


@pytest.mark.parametrize("host", ["magic.shyfai.cn", "magic.shyfai.com"])
def test_owned_storage_aliases_read_from_internal_minio_without_public_round_trip(monkeypatch, host):
    from app.services.image_thumbnails import _source_download_url, settings
    monkeypatch.setattr(settings, "minio_public_endpoint", "https://magic.shyfai.cn")
    monkeypatch.setattr(settings, "minio_bucket", "image2-assets")
    monkeypatch.setattr(settings, "minio_endpoint", "minio:9000")
    monkeypatch.setattr(settings, "minio_secure", False)
    assert _source_download_url(f"https://{host}/image2-assets/images/file%20name.png") == "http://minio:9000/image2-assets/images/file%20name.png"
    foreign = "https://external.example.test/image2-assets/images/source.png"
    assert _source_download_url(foreign) == foreign


async def test_twenty_queued_thumbnails_do_not_block_other_database_requests(previews, monkeypatch):
    import asyncio
    import threading
    client, _, webp, sessions, engine = previews
    release = threading.Event()
    entered = threading.Event()
    def blocked_thumbnail(task_id, source_url):
        entered.set()
        assert release.wait(timeout=5), "test did not release thumbnail worker"
        return webp
    monkeypatch.setattr(catalog, "get_or_create_thumbnail", blocked_thumbnail)
    requests = [asyncio.create_task(client.get(thumbnail_path(7, SOURCE))) for _ in range(20)]
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.sleep(0.1)
        async def independent_query():
            async with sessions() as db:
                return await db.scalar(text("SELECT 1"))
        assert await asyncio.wait_for(independent_query(), timeout=0.5) == 1
        assert engine.sync_engine.pool.checkedout() == 0
    finally:
        release.set()
        responses = await asyncio.gather(*requests, return_exceptions=True)
    assert all(getattr(response, "status_code", 0) == 200 for response in responses)
