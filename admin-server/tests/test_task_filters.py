import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_admin, get_db
from app.main import app
from app.models.admin_user import AdminRole


@pytest.fixture
async def task_client():
    url = os.environ["TEST_DATABASE_URL"]
    assert "test" in url.rsplit("/", 1)[-1]
    schema = "admin_task_filters_" + uuid4().hex
    bootstrap = create_async_engine(url)
    async with bootstrap.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        for table in ["users", "image_models", "image_tasks", "admin_audit_logs"]:
            await conn.execute(text(f'CREATE TABLE {schema}.{table} (LIKE public.{table} INCLUDING ALL)'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        await db.execute(text("INSERT INTO users(id,site_id,username,email,password_hash) VALUES(1,1,'张三','one@test.invalid','unused'),(2,1,'张三店','two@test.invalid','unused'),(3,1,'100%用户','three@test.invalid','unused'),(4,2,'张三','other@test.invalid','unused')"))
        await db.execute(text("INSERT INTO image_models(id,site_id,provider_id,name,code,vendor_model,work_type) VALUES(5,1,1,'测试生图模型','test','test','text_to_image'),(6,2,1,'另一站模型','other','other','text_to_image')"))
        statuses = [(1,1,s) for s in ["succeeded"]*3+["failed"]*2+["refunded","pending","queued","running"]] + [(2,1,s) for s in ["succeeded","succeeded","failed"]] + [(3,1,"failed"),(4,2,"failed"),(4,2,"succeeded")]
        for i,(user_id,site_id,status) in enumerate(statuses,1):
            await db.execute(text("INSERT INTO image_tasks(id,task_no,user_id,site_id,model_id,work_type,prompt,status,created_at,timeout_seconds) VALUES(:id,:task,:user,:site,:model,'batch_generate',:prompt,:status,:created,180)"), {
                "id":i,"task":f"IMG-{i}","user":user_id,"site":site_id,"model":5 if site_id==1 else 6,"prompt":"客厅" if user_id==1 else "草地","status":status,"created":datetime(2026,10,7,tzinfo=timezone.utc)})
        await db.commit()
    identity = SimpleNamespace(id=1,username="reviewer",site_id=1,system_super_admin=False,role=AdminRole.operator)
    async def database():
        async with sessions() as db:
            yield db
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_admin] = lambda: identity
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
            yield client, identity
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
        await engine.dispose()
        async with bootstrap.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await bootstrap.dispose()


async def listing(client, **params):
    response = await client.get("/admin/image-tasks",params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.parametrize("status,count,expected",[("succeeded",5,{"succeeded"}),("failed",5,{"failed","refunded"}),("refunded",1,{"refunded"}),("pending",1,{"pending"}),("queued",1,{"queued"}),("running",1,{"running"})])
async def test_status_filters_count_entire_scoped_result(task_client,status,count,expected):
    result = await listing(task_client[0],status=status,page_size=2)
    assert result["total"] == count and len(result["items"]) == min(count,2)
    assert {row["status"] for row in result["items"]} <= expected
    assert all(row["user_id"] != 4 for row in result["items"])


async def test_user_name_id_status_and_keyword_can_be_combined(task_client):
    client,_ = task_client
    assert (await listing(client,user_id=1))["total"] == 9
    assert (await listing(client,username=" 张三 "))["total"] == 12
    result = await listing(client,user_id=1,status="succeeded",username="张三",keyword="测试生图模型")
    assert result["total"] == 3 and all(row["user_id"] == 1 for row in result["items"])
    result = await listing(client,username="张三",status="failed",keyword="客厅")
    assert result["total"] == 3 and all(row["user_id"] == 1 for row in result["items"])
    assert (await listing(client,username="100%"))["total"] == 1
    assert (await listing(client,user_id=1,keyword="IMG-9"))["total"] == 1


async def test_no_match_cross_site_ids_and_whitespace_do_not_broaden_scopes(task_client):
    client,_ = task_client
    for params in [{"user_id":4},{"username":"不存在"},{"user_id":1,"username":"100%"},{"status":"succeeded","keyword":"不存在"}]:
        result = await listing(client,**params)
        assert result["total"] == 0 and result["items"] == []
    assert (await listing(client,keyword="  ",username="  "))["total"] == 13


async def test_equal_timestamps_have_stable_pages_and_filters_are_preserved(task_client):
    client,_ = task_client
    rows=[]
    for page in range(1,4):
        result=await listing(client,status="failed",username="张三",page_no=page,page_size=2)
        assert result["total"] == 4
        rows.extend(result["items"])
    assert len({row["id"] for row in rows}) == len(rows) == 4
    assert [row["id"] for row in rows] == sorted([row["id"] for row in rows],reverse=True)


async def test_system_super_admin_retains_existing_cross_site_scope(task_client):
    client,identity = task_client
    identity.system_super_admin=True
    assert (await listing(client))["total"] == 15
    result=await listing(client,status="failed",user_id=4)
    assert result["total"] == 1 and result["items"][0]["user_id"] == 4


@pytest.mark.parametrize("params",[{"status":"success"},{"user_id":0},{"user_id":-1},{"user_id":"NaN"},{"user_id":9223372036854775808},{"page_size":101},{"username":"x"*101}])
async def test_invalid_filters_are_rejected(task_client,params):
    assert (await task_client[0].get("/admin/image-tasks",params=params)).status_code == 422


async def test_query_still_requires_authenticated_admin(task_client):
    app.dependency_overrides.pop(get_current_admin)
    assert (await task_client[0].get("/admin/image-tasks?status=failed&user_id=1")).status_code == 401


@pytest.fixture
async def review_client(task_client):
    async for db in app.dependency_overrides[get_db]():
        await db.execute(text("UPDATE image_tasks SET output_image_url='https://example.invalid/result.png' WHERE status='succeeded'"))
        await db.execute(text("UPDATE image_tasks SET is_gallery_featured=true WHERE id IN (1,2,11,15)"))
        await db.execute(text("UPDATE image_tasks SET gallery_featured_by=1 WHERE id IN (2,3,15)"))
        await db.execute(text("UPDATE image_tasks SET deleted_at=now() WHERE id=11"))
        await db.commit()
    return task_client


async def test_gallery_filters_count_and_combine_with_task_filters(review_client):
    client, _ = review_client
    for state, ids in [("pending", [1]), ("approved", [2]), ("rejected", [3])]:
        result = await listing(client, gallery_review_status=state, status="succeeded", username="张三", page_size=1)
        assert result["total"] == 1
        assert [row["id"] for row in result["items"]] == ids
        assert result["items"][0]["gallery_review_status"] == state
        assert result["items"][0]["is_gallery_featured"] == (state == "approved")
    assert (await listing(client, gallery_review_status="pending", user_id=4))["total"] == 0
    assert (await client.get("/admin/image-tasks?gallery_review_status=invalid")).status_code == 422


async def test_gallery_review_approve_reject_audit_and_tenant_boundary(review_client):
    client, identity = review_client
    assert (await client.patch("/admin/image-tasks/1/gallery", json={"featured": True})).status_code == 200
    assert (await listing(client, gallery_review_status="approved"))["total"] == 2
    assert (await client.patch("/admin/image-tasks/1/gallery", json={"featured": False})).status_code == 400
    assert (await client.patch("/admin/image-tasks/1/gallery", json={"featured": False, "reason": "内容不适合公开"})).status_code == 200
    assert (await listing(client, gallery_review_status="rejected"))["total"] == 2
    async for db in app.dependency_overrides[get_db]():
        logs = (await db.execute(text("SELECT action, reason FROM admin_audit_logs ORDER BY id"))).all()
        assert [row.action for row in logs] == ["feature_gallery_task", "unfeature_gallery_task"]
        assert "内容不适合公开" in logs[-1].reason
    for task_id in [11, 15, 9999]:
        assert (await client.patch(f"/admin/image-tasks/{task_id}/gallery", json={"featured": True})).status_code == 404
    for task_id in [3, 4, 10]:
        assert (await client.patch(f"/admin/image-tasks/{task_id}/gallery", json={"featured": True})).status_code == 400
    assert (await client.patch("/admin/image-tasks/2/gallery", json={"featured": "false"})).status_code == 400
    identity.role = AdminRole.finance
    assert (await client.patch("/admin/image-tasks/2/gallery", json={"featured": True})).status_code == 403
