import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.api.endpoints.dashboard import shared_metadata, users_table as u, image_tasks_table as t, credit_ledger_table as l, recharge_orders_table as r
from app.services.dashboard_analytics import analytics_window, load_analytics
NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)

@pytest.fixture
async def db():
    url = os.environ.get("DASHBOARD_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DASHBOARD_TEST_DATABASE_URL must point to an isolated test database")
    assert url.rsplit("/", 1)[-1] == "dashboard_test"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(shared_metadata.drop_all)
        await connection.run_sync(shared_metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()

@pytest.mark.parametrize("days", [7, 15, 30])
def test_beijing_window(days):
    start, end = analytics_window(days, NOW)
    assert end == NOW
    assert start == datetime(2026, 10, 17, 16, tzinfo=UTC) - timedelta(days=days - 1)

async def test_scope_refunds_dates_and_no_join_multiplication(db):
    start, _ = analytics_window(7, NOW)
    await db.execute(u.insert(), [dict(id=i, site_id=2 if i == 3 else 1, username=f"u{i}", created_at=start, deleted_at=NOW if i == 4 else None) for i in range(1, 5)])
    await db.execute(t.insert(), [dict(id=i, user_id=1, site_id=1, created_at=NOW-timedelta(hours=1)) for i in range(1, 4)])
    await db.execute(r.insert(), [dict(id=i, user_id=1, site_id=1, status="paid", amount_cents=1250, paid_at=NOW-timedelta(hours=1), created_at=start-timedelta(days=1)) for i in (1, 2)])
    def entry(id, user, amount, direction="debit", biz="image_task", key="", at=start):
        return dict(id=id, user_id=user, amount=Decimal(amount), direction=direction, biz_type=biz, idempotency_key=key or f"image-task:debit:{id}", created_at=at)
    await db.execute(l.insert(), [entry(1,1,"100.25"), entry(2,1,"20.10","credit","refund","image-task:refund:1"), entry(3,2,"50"), entry(4,3,"999"), entry(5,4,"999"), entry(6,1,"500","credit","recharge"), entry(7,1,"500","debit","admin_adjustment"), entry(8,1,"900",at=start-timedelta(seconds=1)), entry(9,1,"900",at=NOW), entry(10,1,"5","credit","refund","unrelated")])
    result = await load_analytics(db, SimpleNamespace(system_super_admin=False, site_id=1), 7, now=NOW)
    totals = result["totals"]
    assert (totals["new_users"],totals["active_users"],totals["tasks"],totals["paid_users"],totals["revenue_cents"]) == (2,1,3,1,2500)
    assert totals["net_credits"] == Decimal("130.15")
    assert len(result["daily"]) == 7
    assert result["daily"][0]["date"] == "2026-10-12"
    assert result["daily"][1]["new_users"] == 0
    assert [row["user_id"] for row in result["consumption_ranking"]] == [1,2]
    assert result["consumption_ranking"][0]["net_credits"] == Decimal("80.15")
    all_sites = await load_analytics(db, SimpleNamespace(system_super_admin=True), 7, now=NOW)
    assert all_sites["consumption_ranking"][0]["user_id"] == 3
    assert all_sites["totals"]["new_users"] == 3

async def test_negative_cross_period_refund_and_empty_days(db):
    await db.execute(u.insert().values(id=1,site_id=1,username="u",created_at=NOW-timedelta(days=100)))
    await db.execute(l.insert().values(id=1,user_id=1,amount=Decimal("12.50"),direction="credit",biz_type="refund",idempotency_key="image-task:refund:old",created_at=NOW-timedelta(hours=1)))
    result = await load_analytics(db, SimpleNamespace(system_super_admin=False,site_id=1),15,now=NOW)
    assert result["totals"]["net_credits"] == Decimal("-12.50")
    assert result["consumption_ranking"] == []
    assert len(result["daily"]) == 15
    empty = await load_analytics(db, SimpleNamespace(system_super_admin=False,site_id=2),30,now=NOW)
    assert len(empty["daily"]) == 30
    assert all(value == 0 for value in empty["totals"].values())

async def test_http_period_validation_and_auth_dependency(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.api.endpoints.dashboard import router, get_current_admin, get_db
    from app.services import dashboard_analytics
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(system_super_admin=False, site_id=1)
    app.dependency_overrides[get_db] = lambda: None
    async def fake_load(db, admin, days, *, day_offset=0):
        return {"days": days, "day_offset": day_offset}
    monkeypatch.setattr(dashboard_analytics, "load_analytics", fake_load)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for days in (1,7,15,30):
            response = await client.get(f"/analytics?days={days}")
            assert response.status_code == 200, response.text
            assert response.json()["data"]["days"] == days
        yesterday = await client.get("/analytics?days=1&day_offset=1")
        assert yesterday.status_code == 200
        assert yesterday.json()["data"] == {"days": 1, "day_offset": 1}
        assert (await client.get("/analytics?days=7&day_offset=1")).status_code == 422
        assert (await client.get("/analytics?days=90")).status_code == 422


def test_today_and_yesterday_boundaries():
    assert analytics_window(1, NOW) == (datetime(2026, 10, 17, 16, tzinfo=UTC), NOW)
    assert analytics_window(1, NOW, day_offset=1) == (
        datetime(2026, 10, 16, 16, tzinfo=UTC), datetime(2026, 10, 17, 16, tzinfo=UTC))

async def test_yesterday_excludes_today(db):
    boundary = datetime(2026, 10, 17, 16, tzinfo=UTC)
    await db.execute(u.insert(), [dict(id=i,site_id=1,username=f"u{i}",created_at=at) for i,at in enumerate((boundary-timedelta(days=1), boundary-timedelta(seconds=1),boundary),1)])
    result = await load_analytics(db, SimpleNamespace(system_super_admin=False,site_id=1),1,now=NOW,day_offset=1)
    assert result["totals"]["new_users"] == 2
    assert len(result["daily"]) == 1
    assert result["daily"][0]["date"] == "2026-10-17"
    assert result["generated_at"] == NOW.isoformat()
