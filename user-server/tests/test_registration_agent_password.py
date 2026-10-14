from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.encrypted_credentials import EncryptedCredential
from app.services import agent_provisioning as service


@pytest.mark.asyncio
async def test_new_wallet_uses_registration_password(monkeypatch):
    account = SimpleNamespace(agent_user_id=None, agent_password=None)
    monkeypatch.setattr(service, "_account_row", AsyncMock(return_value=account))
    create = AsyncMock(return_value=SimpleNamespace(id=7, email="new@example.test"))
    monkeypatch.setattr(service, "_create_wallet_user", create)
    monkeypatch.setattr(service, "_configured_group_ids", lambda config: [])
    await service._ensure_wallet(
        None, client=None, config=None, owner=None, team_id=1,
        password="Registration-password-123",
    )
    assert create.call_args.kwargs["password"] == "Registration-password-123"
    assert account.agent_password == "Registration-password-123"


@pytest.mark.asyncio
async def test_existing_wallet_password_is_not_replaced(monkeypatch):
    account = SimpleNamespace(agent_user_id=7, agent_password="existing-secret")
    monkeypatch.setattr(service, "_account_row", AsyncMock(return_value=account))
    monkeypatch.setattr(service, "_configured_group_ids", lambda config: [])
    await service._ensure_wallet(
        None, client=None, config=None, owner=None, team_id=1,
        password="Registration-password-123",
    )
    assert account.agent_password == "existing-secret"


def test_credentials_encrypt_and_read_legacy():
    field = EncryptedCredential()
    password = "密" * 128
    stored = field.process_bind_param(password, None)
    assert password not in stored
    assert field.process_result_value(stored, None) == password
    assert field.process_result_value("legacy-secret", None) == "legacy-secret"
    assert field.process_bind_param(None, None) is None
    assert field.process_result_value(None, None) is None


def test_database_roundtrip_keeps_password_out_of_raw_storage():
    from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select, text

    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table("credentials", metadata, Column("id", Integer, primary_key=True),
                  Column("password", EncryptedCredential()))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert().values(id=1, password="registration-secret"))
        stored = connection.scalar(text("SELECT password FROM credentials WHERE id = 1"))
        assert stored.startswith("enc:v1:")
        assert "registration-secret" not in stored
        assert connection.scalar(select(table.c.password)) == "registration-secret"
    engine.dispose()
