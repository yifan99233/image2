import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.api.routes import redemption
from app.core.exceptions import BusinessError
from app.db.base import Base
from app.models.user import User
from app.models.credit import UserCreditAccount, CreditLedger
from app.models.redemption import RedemptionCode
from app.models.agent import AgentConfig
from app.services.agent_openapi import AgentAPIError

@pytest.fixture
async def sessions(monkeypatch):
    url = os.environ['TEST_DATABASE_URL']
    schema = 'redeem_' + uuid4().hex
    bootstrap = create_async_engine(url)
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_async_engine(url, connect_args={'server_settings': {'search_path': schema}})
    tables = [User.__table__, UserCreditAccount.__table__, CreditLedger.__table__, RedemptionCode.__table__, AgentConfig.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        for uid in (1, 2):
            db.add(User(id=uid, site_id=1, username=f'user{uid}', email=f'{uid}@test.invalid', password_hash='unused'))
        await db.flush()
        for uid in (1, 2):
            db.add(UserCreditAccount(user_id=uid, balance=20, total_recharged=20))
        await db.commit()
    monkeypatch.setattr(redemption, '_billing_context', AsyncMock(return_value=None))
    yield factory
    await engine.dispose()
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    await bootstrap.dispose()

async def seed(sessions, **values):
    raw = uuid4().hex + 'ABCDEF12'
    async with sessions() as db:
        row = RedemptionCode(id=str(uuid4()), site_id=1, batch_id=str(uuid4()), code_hash=redemption.code_digest(raw), code_hint=raw[-8:], amount=100, created_by=1, status='unused')
        for key, value in values.items(): setattr(row, key, value)
        db.add(row)
        await db.commit()
    return raw, row.id

async def claim(sessions, code, uid=1, site_id=1):
    async with sessions() as db:
        return await redemption.redeem_credit(db, SimpleNamespace(id=uid, site_id=site_id), code)

async def test_redeem_is_gift_and_retry_is_idempotent(sessions):
    code, _ = await seed(sessions)
    assert (await claim(sessions, code.lower()))['amount'] == 100
    await claim(sessions, code)
    async with sessions() as db:
        account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == 1))
        assert (account.balance, account.gift_balance, account.total_gifted, account.total_recharged) == (120, 100, 100, 20)
        assert await db.scalar(select(func.count()).select_from(CreditLedger)) == 1
        ledger = await db.scalar(select(CreditLedger))
        assert ledger.gift_amount == 100 and ledger.biz_type == 'redemption_gift'

@pytest.mark.parametrize('values,expected', [({'status': 'disabled'}, 40061), ({'expires_at': datetime.now(timezone.utc) - timedelta(days=1)}, 40063), ({'status': 'redeemed', 'redeemed_by': 2}, 40062), ({'status': 'processing', 'redeemed_by': 2}, 40062)])
async def test_invalid_states_never_credit(sessions, values, expected):
    code, _ = await seed(sessions, **values)
    with pytest.raises(BusinessError) as caught: await claim(sessions, code)
    assert caught.value.code == expected
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CreditLedger)) == 0

async def test_site_isolation(sessions):
    code, _ = await seed(sessions)
    with pytest.raises(BusinessError) as caught: await claim(sessions, code, site_id=2)
    assert caught.value.code == 40060

async def test_concurrent_different_users_only_one_wins(sessions):
    code, _ = await seed(sessions)
    results = await asyncio.gather(claim(sessions, code, 1), claim(sessions, code, 2), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    async with sessions() as db:
        assert await db.scalar(select(func.sum(UserCreditAccount.gift_balance))) == 100
        assert await db.scalar(select(func.count()).select_from(CreditLedger)) == 1

async def test_concurrent_same_user_only_credits_once(sessions):
    code, _ = await seed(sessions)
    await asyncio.gather(*(claim(sessions, code) for _ in range(6)))
    async with sessions() as db:
        assert await db.scalar(select(func.sum(UserCreditAccount.gift_balance))) == 100
        assert await db.scalar(select(func.count()).select_from(CreditLedger)) == 1

async def test_remote_lost_response_is_bound_and_retries_same_operation(sessions, monkeypatch):
    code, code_id = await seed(sessions)
    config = AgentConfig(site_id=1, is_enabled=True, base_url='https://example.invalid', credit_to_agent_rate=Decimal('10'))
    async with sessions() as db:
        db.add(config)
        await db.commit()
    context = SimpleNamespace(config=config, account=SimpleNamespace(user_id=1, agent_user_id=321))
    monkeypatch.setattr(redemption, '_billing_context', AsyncMock(return_value=context))
    credited, calls = set(), []
    class Client:
        def __init__(self, config): pass
        def add_balance(self, **kwargs):
            calls.append(kwargs); credited.add(kwargs['idempotency_key'])
            if len(calls) == 1: raise AgentAPIError('simulated response lost')
    monkeypatch.setattr(redemption, 'AgentOpenAPIClient', Client)
    with pytest.raises(BusinessError): await claim(sessions, code)
    async with sessions() as db:
        row = await db.get(RedemptionCode, code_id)
        assert row.status == 'processing' and row.redeemed_by == 1
        assert await db.scalar(select(func.count()).select_from(CreditLedger)) == 0
    with pytest.raises(BusinessError): await claim(sessions, code, 2)
    context.account.agent_user_id = 999
    await claim(sessions, code)
    assert len(credited) == 1
    assert all(call['agent_user_id'] == 321 and call['amount'] == Decimal('10') for call in calls)

async def test_cannot_credit_someone_elses_team_wallet(sessions, monkeypatch):
    code, _ = await seed(sessions)
    monkeypatch.setattr(redemption, '_billing_context', AsyncMock(return_value=SimpleNamespace(account=SimpleNamespace(user_id=2))))
    with pytest.raises(BusinessError) as error: await claim(sessions, code)
    assert error.value.code == 40064

async def test_gift_spend_and_refund_restore_original_source(sessions, monkeypatch):
    from app.api.routes import catalog
    code, _ = await seed(sessions)
    await claim(sessions, code)
    monkeypatch.setattr(catalog, 'debit_image_task_balance', AsyncMock(return_value=None))
    monkeypatch.setattr(catalog, 'refund_image_task_balance', AsyncMock(return_value=None))
    async with sessions() as db:
        await catalog.debit_image_task_credits(db, 1, 'gift-test-task', 110)
        await db.commit()
        account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == 1))
        assert account.balance == 10 and account.gift_balance == 0
        await catalog.refund_image_task_credits(db, 1, 'gift-test-task', 110)
        await db.commit()
        assert account.balance == 120 and account.gift_balance == 100
        await catalog.refund_image_task_credits(db, 1, 'gift-test-task', 110)
        await db.commit()
        assert account.balance == 120 and account.gift_balance == 100

async def test_http_redemption_payload_and_authentication(sessions, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.main import create_app
    from app.api.deps import get_current_user
    from app.db.session import get_db
    code, _ = await seed(sessions)
    app = create_app()
    async def database():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(redemption, 'login_rate_limit_key', AsyncMock(return_value=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        assert (await client.post('/credits/redeem', json={'code': code})).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, site_id=1)
        response = await client.post('/credits/redeem', json={'code': code})
        assert response.status_code == 200
        assert response.json()['data']['balance_type'] == 'gift'
        assert response.json()['data']['amount'] == 100
        monkeypatch.setattr(redemption, 'login_rate_limit_key', AsyncMock(return_value=False))
        assert (await client.post('/credits/redeem', json={'code': code})).status_code == 429
