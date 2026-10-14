from types import SimpleNamespace

import pytest

from app.api.routes.materials import normalize_upload_mode
from app.core.exceptions import BusinessError
from app.services import material_billing


class FakeSession:
    def __init__(self, scalar_values=None):
        self.added = []
        self.scalar_values = list(scalar_values or [])

    def add(self, value):
        self.added.append(value)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None


def test_normalize_upload_mode_defaults_to_local():
    assert normalize_upload_mode(None) == "local"
    assert normalize_upload_mode(" CDN ") == "cdn"


def test_normalize_upload_mode_rejects_unknown_value():
    with pytest.raises(BusinessError) as exc_info:
        normalize_upload_mode("third-party")
    assert exc_info.value.code == 40043


async def test_material_cdn_upload_debits_one_credit_with_own_ledger(monkeypatch):
    account = SimpleNamespace(id=3, balance=5, gift_balance=2, total_consumed=0, version=1)
    db = FakeSession()

    async def no_external_debit(_db, **_kwargs):
        return None

    async def get_account(_db, _user_id):
        return account

    monkeypatch.setattr(material_billing, "debit_image_task_balance", no_external_debit)
    monkeypatch.setattr(material_billing, "_get_or_create_credit_account_for_update", get_account)

    receipt = await material_billing.debit_material_cdn_upload(db, user_id=12, credit_amount=1)

    assert receipt.credit_amount == 1
    assert account.balance == 4
    assert account.gift_balance == 1
    assert account.total_consumed == 1
    assert db.added[0].biz_type == "material_cdn_upload"
    assert db.added[0].description == "CDN 素材上传扣除 1 积分"


async def test_material_cdn_upload_rejects_insufficient_local_balance(monkeypatch):
    account = SimpleNamespace(id=3, balance=0, gift_balance=0, total_consumed=0, version=1)

    async def no_external_debit(_db, **_kwargs):
        return None

    async def get_account(_db, _user_id):
        return account

    monkeypatch.setattr(material_billing, "debit_image_task_balance", no_external_debit)
    monkeypatch.setattr(material_billing, "_get_or_create_credit_account_for_update", get_account)

    with pytest.raises(BusinessError) as exc_info:
        await material_billing.debit_material_cdn_upload(FakeSession(), user_id=12, credit_amount=1)

    assert exc_info.value.code == 40030
