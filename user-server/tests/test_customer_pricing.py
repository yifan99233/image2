import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select, text, update, func

from app.api.routes import catalog
from app.models.agent import AgentConfig
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.image_batch_upload import ImageBatchUpload
from app.models.user import User
from app.services.customer_pricing import calculate_price
from app.services import image_batch_uploads as uploads
from app.core.responses import StandardResponse, ok
from app.schemas.credits import CreditBalanceOut
from test_batch_groups import sessions
from test_batch_progress import batch_client
from test_batch_uploads import manifest, prepare_model, accept


def test_typed_balance_response_preserves_numeric_json_contract():
    result = StandardResponse[CreditBalanceOut](code=0, message="ok", data=CreditBalanceOut(
        balance=Decimal("99.20"), gift_balance=Decimal(".50"), total_recharged=100, total_consumed=Decimal(".80")))
    assert json.loads(result.model_dump_json())["data"] == {
        "balance": 99.2, "gift_balance": 0.5, "total_recharged": 100, "total_consumed": 0.8, "total_gifted": 0}


async def configure(db, *, base=1, surcharge="2", rate="0.8", site_id=1, user_id=1, expiry=None):
    await db.execute(text("UPDATE image_model_prices SET credit_cost=:base, fixed_surcharge=:fee WHERE model_id=5"),
                     {"base": base, "fee": Decimal(surcharge)})
    tier = await db.scalar(text("INSERT INTO customer_vip_tiers(site_id,name,discount_rate) VALUES(:site,'VIP',:rate) RETURNING id"),
                           {"site": site_id, "rate": Decimal(rate)})
    await db.execute(text("INSERT INTO customer_vip_memberships(user_id,site_id,tier_id,expires_at) VALUES(:user,:site,:tier,:expiry)"),
                     {"user": user_id, "site": site_id, "tier": tier, "expiry": expiry})
    await db.commit()
    return tier


@pytest.mark.parametrize("base,rate,fee,expected", [(10, ".8", 2, "10.00"), (1, ".8", 2, "2.80"), (7, ".3333", ".12", "2.45")])
def test_round_once_per_output(base, rate, fee, expected):
    assert calculate_price(base, rate, fee) == Decimal(expected)
    assert calculate_price(base, rate, fee) * 20000 == Decimal(expected) * 20000


async def test_quote_json_numbers_single_debit_and_original_refund(sessions, batch_client):
    async with sessions() as db:
        await configure(db)
    response = await batch_client.post("/models/5/quote", json=manifest(1))
    assert response.status_code == 200
    quote = response.json()["data"]
    assert quote["credit_cost"] == 2.8
    assert quote["pricing"]["discount_rate"] == "0.8000"
    async with sessions() as db:
        user = await db.get(User, 1)
        result = await catalog.create_image_task({**manifest(1), "work_type": "text_to_image", "prompt": "test"}, BackgroundTasks(), user, db)
        task = (await db.execute(select(catalog.image_tasks_table).where(catalog.image_tasks_table.c.id == result.data["id"]))).mappings().one()
        account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == 1))
        assert account.balance == Decimal("19997.20")
        assert task["pricing_snapshot"]["fixed_surcharge"] == "2.00"
        await db.execute(text("UPDATE image_model_prices SET fixed_surcharge=99"))
        await db.execute(text("UPDATE customer_vip_tiers SET discount_rate=0.5"))
        await catalog.refund_image_task_credits(db, 1, task["task_no"], task["credit_cost"])
        await db.commit()
        await catalog.refund_image_task_credits(db, 1, task["task_no"], task["credit_cost"])
        await db.commit()
        await db.refresh(account)
        assert account.balance == 20000
        assert account.gift_balance == 20
        assert account.total_consumed == 0
        assert await db.scalar(select(func.count()).select_from(CreditLedger)) == 2


@pytest.mark.parametrize("mode", ["expired", "disabled", "other_site", "ordinary"])
async def test_ineligible_vip_uses_base_plus_surcharge(sessions, mode):
    async with sessions() as db:
        tier = await configure(db, site_id=2 if mode == "other_site" else 1,
            expiry=datetime.now(timezone.utc) - timedelta(seconds=1) if mode == "expired" else None)
        if mode == "disabled":
            await db.execute(text("UPDATE customer_vip_tiers SET is_active=false WHERE id=:id"), {"id": tier})
        if mode == "ordinary":
            await db.execute(text("DELETE FROM customer_vip_memberships"))
        result = await catalog.quote(5, manifest(1), await db.get(User, 1), db)
        assert result.data["credit_cost"] == Decimal("3.00")


async def test_shared_wallet_uses_owner_vip_only_when_external_billing_enabled(sessions):
    async with sessions() as db:
        await configure(db)
        db.add(AgentConfig(site_id=1, is_enabled=True, image_billing_enabled=True))
        await db.execute(text("INSERT INTO user_team_members(site_id,team_id,user_id,role) VALUES(1,1,2,'member')"))
        member = await db.get(User, 2)
        member.active_team_id = 1
        await db.commit()
        result = await catalog.quote(5, manifest(1), member, db)
        assert result.data["credit_cost"] == Decimal("2.80")
        assert result.data["pricing"]["payer_user_id"] == 1
        await db.execute(update(AgentConfig).values(image_billing_enabled=False))
        result = await catalog.quote(5, manifest(1), member, db)
        assert result.data["credit_cost"] == Decimal("3.00")
        assert result.data["pricing"]["payer_user_id"] == 2


async def test_20000_tasks_keep_accepted_price_after_vip_changes(sessions):
    async with sessions() as db:
        await configure(db)
        await db.execute(update(UserCreditAccount).values(balance=100000))
        await db.commit()
    value = manifest(20000)
    await accept(sessions, value)
    async with sessions() as db:
        job = await db.scalar(select(ImageBatchUpload).where(ImageBatchUpload.batch_id == value["batch_id"]))
        assert job.payload["credit_cost"] == "2.80"
        await db.execute(text("UPDATE customer_vip_tiers SET discount_rate=0.5"))
        await db.execute(text("UPDATE image_model_prices SET fixed_surcharge=20"))
        await uploads.materialize_tasks(db, job, None)
        account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == 1))
        assert account.balance == Decimal("44000.00")
        assert account.total_consumed == Decimal("56000.00")
        assert await db.scalar(select(func.count()).select_from(catalog.image_tasks_table).where(catalog.image_tasks_table.c.credit_cost == Decimal("2.80"))) == 20000
        assert await db.scalar(select(func.sum(CreditLedger.amount))) == Decimal("56000.00")


async def test_retry_quote_changes_when_tier_or_surcharge_changes(sessions):
    async with sessions() as db:
        await configure(db)
        user = await db.get(User, 1)
        result = await catalog.create_batch_image_tasks({**manifest(1), "prompt": "test"}, BackgroundTasks(), user, db)
        await db.execute(update(catalog.image_tasks_table).values(status="failed"))
        sources = await catalog.retry_source_tasks(db, user, result.data["batch_id"])
        priced, token = await catalog.price_retry_sources(db, user, sources)
        assert priced[0]["credit_cost"] == Decimal("2.80")
        await db.execute(text("UPDATE customer_vip_tiers SET discount_rate=0.5"))
        repriced, new_token = await catalog.price_retry_sources(db, user, sources)
        assert repriced[0]["credit_cost"] == Decimal("2.50")
        assert token != new_token


async def test_external_wallet_fractional_batch_and_refund_use_original_receipt(sessions, monkeypatch):
    from test_batch_uploads import external_billing
    from app.services.sub2_image_billing import refund_image_task_balance
    calls, effects, _ = await external_billing(sessions, monkeypatch)
    async with sessions() as db:
        await configure(db)
    value = manifest(3)
    await accept(sessions, value)
    async with sessions() as db:
        job = await db.scalar(select(ImageBatchUpload).where(ImageBatchUpload.batch_id == value["batch_id"]))
        await uploads.process_locked_upload(db, job.id)
        assert calls[0][1]["amount"] == Decimal("0.0840")
        task = (await db.execute(select(catalog.image_tasks_table))).mappings().first()
        await db.execute(update(AgentConfig).values(credit_to_agent_rate=200))
        await db.commit()
        await refund_image_task_balance(db, task_no=task["task_no"])
        await db.commit()
        assert calls[-1][1]["amount"] == Decimal("0.0280")
        await refund_image_task_balance(db, task_no=task["task_no"])
        assert len(effects) == 2


async def test_migration_preserves_legacy_prices_and_refuses_fractional_downgrade(sessions):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    root = Path(__file__).resolve().parents[2]
    def migration(path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    user_migration = migration(root / "user-server/alembic/versions/20261012_0100_fractional_credits.py")
    admin_migration = migration(root / "admin-server/alembic/versions/20261012_0100_customer_vip_prices.py")
    async with sessions() as db:
        connection = await db.connection()
        def round_trip(sync):
            with Operations.context(MigrationContext.configure(sync)):
                user_migration.downgrade()
                admin_migration.downgrade()
                admin_migration.upgrade()
                user_migration.upgrade()
        await connection.run_sync(round_trip)
        assert await db.scalar(text("SELECT credit_cost FROM image_model_prices LIMIT 1")) == 7
        assert await db.scalar(text("SELECT fixed_surcharge FROM image_model_prices LIMIT 1")) == 0
        assert await db.scalar(text("SELECT balance FROM user_credit_accounts WHERE user_id=1")) == 20000
        await db.execute(text("UPDATE user_credit_accounts SET balance=12.34 WHERE user_id=1"))
        def refuse_loss(sync):
            with Operations.context(MigrationContext.configure(sync)):
                with pytest.raises(RuntimeError, match="cannot be rolled back safely"):
                    user_migration.downgrade()
        await connection.run_sync(refuse_loss)
        assert await db.scalar(text("SELECT balance FROM user_credit_accounts WHERE user_id=1")) == Decimal("12.34")
