import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_admin, get_db
from app.api.endpoints import admin_data, customer_vip
from app.api.endpoints.admin_data import create_model_price_version, parse_surcharge
from app.core.exceptions import AppException
from app.models.admin_user import AdminRole
from app.models.model_price import ModelPrice


@pytest.fixture
async def vip_api():
    url = os.environ.get("TEST_DATABASE_URL", "")
    if "test" not in url.rsplit("/", 1)[-1]:
        pytest.skip("Provide an isolated TEST_DATABASE_URL with both services' migrations")
    engine = create_async_engine(url)
    schema = "vip_admin_" + uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        tables = (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))).scalars().all()
        for table in tables:
            await conn.execute(text(f'CREATE TABLE {schema}."{table}" (LIKE public."{table}" INCLUDING ALL)'))
    scoped = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(scoped, expire_on_commit=False)
    async with sessions() as db:
        await db.execute(text("INSERT INTO users(id,site_id,username,email,password_hash) VALUES(1,1,'test','one@test.invalid','unused'),(2,2,'other','two@test.invalid','unused')"))
        await db.execute(text("INSERT INTO image_model_providers(id,site_id,name,code,base_url) VALUES(1,1,'test','test','https://invalid')"))
        await db.execute(text("INSERT INTO image_models(id,site_id,provider_id,name,code,vendor_model,work_type) VALUES(1,1,1,'test','test','test','text_to_image')"))
        await db.commit()
    admin = SimpleNamespace(id=1, site_id=1, username="test", role=AdminRole.super_admin, system_super_admin=False)
    app = FastAPI()
    app.include_router(customer_vip.router)
    app.include_router(admin_data.router)
    @app.exception_handler(AppException)
    async def business_error(_, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=exc.status_code, content={"message": exc.message})
    async def database():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_admin] = lambda: admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test.invalid") as client:
            yield client, admin, sessions
    finally:
        await scoped.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await engine.dispose()


async def test_tier_assignment_expiry_audit_and_site_isolation(vip_api):
    client, admin, sessions = vip_api
    value = {"name": "VIP1", "discount_rate": 0.8, "reason": "测试"}
    response = await client.post("/vip-tiers", json=value)
    assert response.status_code == 200, response.text
    tier_id = response.json()["data"]["id"]
    assert (await client.get("/vip-tiers")).json()["data"][0]["discount_rate"] == 0.8
    assert (await client.post("/vip-tiers", json=value)).status_code == 400
    assignment = {"tier_id": tier_id, "reason": "升级", "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}
    assert (await client.put("/users/1/vip", json=assignment)).status_code == 200
    assert (await client.put("/users/2/vip", json=assignment)).status_code == 404
    assert (await client.get("/vip-tiers?site_id=2")).status_code == 403
    admin.system_super_admin = True
    assert (await client.put("/users/2/vip", json=assignment)).status_code == 400
    admin.system_super_admin = False
    assert (await client.put("/users/1/vip", json={**assignment, "expires_at": "2000-01-01T00:00:00Z"})).status_code == 422
    assert (await client.put(f"/vip-tiers/{tier_id}", json={**value, "is_active": False})).status_code == 200
    assert (await client.put("/users/1/vip", json=assignment)).status_code == 400
    assert (await client.put("/users/1/vip", json={"tier_id": None, "reason": "取消"})).status_code == 200
    async with sessions() as db:
        assert await db.scalar(text("SELECT count(*) FROM customer_vip_memberships")) == 0
        assert await db.scalar(text("SELECT count(*) FROM admin_audit_logs")) == 4


async def test_only_authorized_roles_can_change_vip(vip_api):
    client, admin, _ = vip_api
    admin.role = AdminRole.operator
    assert (await client.get("/vip-tiers")).status_code == 200
    assert (await client.post("/vip-tiers", json={"name": "V", "discount_rate": 0.8, "reason": "test"})).status_code == 403
    assert (await client.put("/users/1/vip", json={"tier_id": None, "reason": "test"})).status_code == 403
    admin.role = AdminRole.finance
    assert (await client.post("/vip-tiers", json={"name": "V", "discount_rate": 0.8, "reason": "test"})).status_code == 200


async def test_surcharge_versions_preserve_existing_fee_for_old_clients(vip_api):
    _, _, sessions = vip_api
    identity = dict(site_id=1, model_id=1, work_type="text_to_image", resolution="1k", aspect_ratio="1:1", output_count=1, reason="test")
    async with sessions() as db:
        first, _, _ = await create_model_price_version(db, **identity, credit_cost=10, fixed_surcharge=Decimal("2.50"))
        second, replaced, created = await create_model_price_version(db, **identity, credit_cost=10, fixed_surcharge=Decimal("3.25"))
        assert created and replaced == [first.id]
        third, _, _ = await create_model_price_version(db, **identity, credit_cost=20)
        assert third.fixed_surcharge == Decimal("3.25")
        same, _, created = await create_model_price_version(db, **identity, credit_cost=20, fixed_surcharge=Decimal("3.25"))
        assert same.id == third.id and not created
        await db.commit()
        assert (await db.scalar(select(ModelPrice).where(ModelPrice.id == second.id))).is_active is False


@pytest.mark.parametrize("fee", ["-1", "NaN", "Infinity", True, "0.001", "100000001"])
def test_surcharge_validation(fee):
    with pytest.raises(AppException):
        parse_surcharge(fee)


async def test_customer_status_filters_apply_before_pagination_and_keep_site_scope(vip_api):
    client, admin, sessions = vip_api
    async with sessions() as db:
        await db.execute(text("INSERT INTO users(id,site_id,username,email,password_hash) SELECT id,1,'customer'||id,'customer'||id||'@test.invalid','unused' FROM generate_series(3,7) id"))
        await db.execute(text("INSERT INTO customer_vip_tiers(id,site_id,name,discount_rate,is_active) VALUES (100,1,'active',0.8,true),(101,1,'disabled',0.7,false),(102,2,'other',0.9,true)"))
        await db.execute(text("INSERT INTO customer_vip_memberships(user_id,site_id,tier_id,expires_at) VALUES (1,1,100,NULL),(2,2,102,NULL),(3,1,100,now()+interval '1 day'),(4,1,100,now()-interval '1 day'),(5,1,101,NULL),(6,1,101,now()-interval '1 day')"))
        await db.commit()
    expected = {"all": {1,3,4,5,6,7}, "active": {1,3}, "expired": {4}, "disabled": {5,6}, "ordinary": {7}}
    for status, ids in expected.items():
        result = await client.get(f"/users?vip_status={status}&page_size=1")
        assert result.status_code == 200, result.text
        data = result.json()["data"]
        assert data["total"] == len(ids)
        found = {data["items"][0]["id"]}
        for page in range(2, len(ids) + 1):
            more = (await client.get(f"/users?vip_status={status}&page_size=1&page_no={page}")).json()["data"]
            found.add(more["items"][0]["id"])
        assert found == ids
    assert (await client.get("/users?vip_status=active&keyword=customer3")).json()["data"]["total"] == 1
    assert (await client.get("/users?vip_status=unknown")).status_code == 422
    admin.system_super_admin = True
    assert (await client.get("/users?vip_status=active")).json()["data"]["total"] == 3
