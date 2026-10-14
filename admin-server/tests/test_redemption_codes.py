import hashlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.endpoints import redemption as api
from app.core.exceptions import AppException
from app.db.base import Base
from app.models.admin_audit_log import AdminAuditLog
from app.models.admin_user import AdminRole
from app.models.redemption import RedemptionBatch, RedemptionCode


def admin(site=1, role=AdminRole.finance):
    return SimpleNamespace(id=site, username=f'admin{site}', site_id=site, system_super_admin=False, role=role)


@pytest.fixture
async def sessions():
    url = os.environ['TEST_DATABASE_URL']
    if 'test' not in url.rsplit('/', 1)[-1]:
        raise RuntimeError('Only isolated test databases are allowed')
    schema = 'admin_redeem_' + uuid4().hex
    bootstrap = create_async_engine(url)
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_async_engine(url, connect_args={'server_settings': {'search_path': schema}})
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[RedemptionBatch.__table__, RedemptionCode.__table__, AdminAuditLog.__table__]))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    await bootstrap.dispose()


@pytest.mark.parametrize('values', [{'amount': 0}, {'amount': 1.5}, {'amount': 1, 'count': 1001}, {'amount': 1, 'count': 0}, {'amount': 1, 'expires_at': datetime.now(timezone.utc) - timedelta(days=1)}])
def test_reject_invalid_generation(values):
    with pytest.raises(ValidationError):
        api.GenerateCodes(request_id=uuid4(), **values)


async def test_bulk_codes_are_unique_hashed_scoped_and_audited(sessions):
    payload = api.GenerateCodes(request_id=uuid4(), amount=37, count=20)
    async with sessions() as db:
        response = await api.generate_codes(payload, None, admin(), db)
        raw = [row['code'] for row in response.data['codes']]
        assert len(set(raw)) == 20
        rows = list(await db.scalars(select(RedemptionCode)))
        assert {row.code_hash for row in rows} == {hashlib.sha256(code.replace('-', '').encode()).hexdigest() for code in raw}
        assert all(row.amount == 37 and row.site_id == 1 for row in rows)
        assert await db.scalar(select(func.count()).select_from(AdminAuditLog)) == 1
        listing = await api.list_codes(None, page=1, page_size=5, status=None, batch_id=None, admin=admin(), db=db)
        assert len(listing.data['items']) == 5 and listing.data['total'] == 20
        assert all('code_hash' not in row and 'code' not in row for row in listing.data['items'])
        other = await api.list_codes(None, page=1, page_size=50, status=None, batch_id=None, admin=admin(2), db=db)
        assert other.data == {'items': [], 'total': 0}


async def test_generation_retry_does_not_generate_another_batch(sessions):
    payload = api.GenerateCodes(request_id=uuid4(), amount=37, count=2)
    async with sessions() as db:
        await api.generate_codes(payload, None, admin(), db)
        with pytest.raises(AppException):
            await api.generate_codes(payload, None, admin(), db)
        assert await db.scalar(select(func.count()).select_from(RedemptionCode)) == 2


async def test_disable_is_scoped_and_cannot_interrupt_credit(sessions):
    async with sessions() as db:
        await api.generate_codes(api.GenerateCodes(request_id=uuid4(), amount=37), None, admin(), db)
        row = await db.scalar(select(RedemptionCode))
        with pytest.raises(AppException):
            await api.disable_code(row.id, None, admin(2), db)
        await db.rollback()
        row = await db.scalar(select(RedemptionCode))
        row.status = 'processing'
        await db.commit()
        with pytest.raises(AppException):
            await api.disable_code(row.id, None, admin(), db)
        await db.rollback()
        row = await db.scalar(select(RedemptionCode))
        row.status = 'unused'
        await db.commit()
        result = await api.disable_code(row.id, None, admin(), db)
        assert result.data['status'] == 'disabled'


async def test_disallowed_role_cannot_manage_codes():
    with pytest.raises(AppException):
        await api.admin_access(admin(role=AdminRole.model_admin))
    assert (await api.admin_access(admin())).role == AdminRole.finance


async def test_unauthenticated_admin_api_is_rejected():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.get('/admin/redemption-codes')
        assert response.status_code == 401

async def test_migration_defaults_existing_accounts_and_widens_credentials(sessions):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    async with sessions() as db:
        connection = await db.connection()
        def migrate(sync):
            sync.execute(text('DROP TABLE redemption_codes, redemption_batches'))
            sync.execute(text('CREATE TABLE user_credit_accounts (id bigint PRIMARY KEY)'))
            sync.execute(text('INSERT INTO user_credit_accounts VALUES (1)'))
            sync.execute(text('CREATE TABLE credit_ledger (id bigint PRIMARY KEY)'))
            sync.execute(text('CREATE TABLE user_agent_accounts (id bigint PRIMARY KEY, agent_password varchar(255))'))
            for filename in ('20260924_0100_agent_credentials.py', '20260924_0200_redemption_codes.py'):
                path = Path(__file__).parents[1] / 'alembic' / 'versions' / filename
                spec = importlib.util.spec_from_file_location('test_migration', path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.op = Operations(MigrationContext.configure(sync))
                module.upgrade()
            row = sync.execute(text('SELECT gift_balance, total_gifted FROM user_credit_accounts WHERE id=1')).one()
            assert tuple(row) == (0, 0)
            sync.execute(text('INSERT INTO user_agent_accounts (id, agent_password) VALUES (1, :password)'), {'password': 'x' * 800})
        await connection.run_sync(migrate)
        await db.commit()

async def test_admin_debit_consumes_gift_without_reclassifying_recharge(monkeypatch):
    from app.services import admin_credit_adjustments as service
    row = SimpleNamespace(id=9, status=service.PENDING, delta=-60, user_id=1, agent_user_id=None,
                          reason='manual debit', admin_id=1)
    account = SimpleNamespace(id=1, balance=100, gift_balance=40, total_recharged=60, total_consumed=0)
    async def load(*args, **kwargs): return row
    async def load_account(*args, **kwargs): return account
    monkeypatch.setattr(service, '_load_adjustment', load)
    monkeypatch.setattr(service, '_credit_account_for_update', load_account)
    statements = []
    class Session:
        async def execute(self, statement): statements.append(statement)
        def add(self, value): pass
        async def commit(self): pass
    result = await service._finalize_adjustment(Session(), adjustment_idempotency_key='test-gift-adjustment', admin=admin())
    assert result.balance_after == 40
    updates = [statement.compile().params for statement in statements if statement.is_update and statement.table.name == 'user_credit_accounts']
    assert updates[0]['gift_balance'] == 0
    assert updates[0]['total_recharged'] == 60
    ledger = next(statement.compile().params for statement in statements if statement.is_insert and statement.table.name == 'credit_ledger')
    assert ledger['gift_amount'] == 40 and ledger['amount'] == 60
