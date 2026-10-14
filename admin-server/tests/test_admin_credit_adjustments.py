import io
import json
import urllib.error
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.endpoints import admin_data
from app.core.exceptions import AppException
from app.services.admin_credit_adjustments import (
    CreditAdjustmentResult,
    _remote_idempotency_key,
    _validate_existing_adjustment,
    display_credit_balance,
)
from app.services.sub2_balance import Sub2BalanceError, Sub2BalanceTarget, change_sub2_balance, to_sub2_amount


def target() -> Sub2BalanceTarget:
    return Sub2BalanceTarget(
        base_url="https://sub2.example.test",
        admin_api_key="admin-key",
        agent_user_id=99,
        credit_to_agent_rate=Decimal("25"),
    )


def test_sub2_balance_change_uses_admin_contract_and_returns_authoritative_balance(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"data": {"balance": "12.4"}}).encode()

    def fake_urlopen(request, timeout):
        captured.update(
            url=request.full_url,
            method=request.method,
            headers=dict(request.header_items()),
            body=json.loads(request.data.decode()),
            timeout=timeout,
        )
        return FakeResponse()

    monkeypatch.setattr("app.services.sub2_balance.urllib.request.urlopen", fake_urlopen)

    balance = change_sub2_balance(
        target(),
        amount=Decimal("0.4000"),
        operation="add",
        idempotency_key="image2-admin-adjustment:req-1",
        notes="后台加款",
    )

    assert balance == Decimal("12.4")
    assert captured["url"] == "https://sub2.example.test/api/v1/admin/users/99/balance"
    assert captured["method"] == "POST"
    assert captured["body"] == {"balance": 0.4, "operation": "add", "notes": "后台加款"}
    assert captured["headers"]["X-api-key"] == "admin-key"
    assert captured["headers"]["Idempotency-key"] == "image2-admin-adjustment:req-1"
    assert captured["timeout"] == 20


def test_sub2_balance_http_client_error_is_exposed_as_admin_input_failure(monkeypatch):
    def fake_urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="https://sub2.example.test",
            code=400,
            msg="bad request",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"insufficient balance"}'),
        )

    monkeypatch.setattr("app.services.sub2_balance.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(Sub2BalanceError) as exc_info:
        change_sub2_balance(
            target(),
            amount=Decimal("1"),
            operation="subtract",
            idempotency_key="image2-admin-adjustment:req-2",
            notes="后台扣款",
        )

    assert exc_info.value.status_code == 400
    assert "insufficient balance" in str(exc_info.value)


def test_credit_conversion_and_remote_display_balance_use_configured_rate():
    assert to_sub2_amount(10, Decimal("25")) == Decimal("0.4000")
    assert display_credit_balance(Decimal("0.4399"), Decimal("25")) == Decimal("10.99")
    assert _remote_idempotency_key("request_123") == "image2-admin-adjustment:request_123"


def test_reusing_idempotency_key_for_different_adjustment_is_rejected():
    row = SimpleNamespace(site_id=1, user_id=49, admin_id=7, delta=100, reason="补款")

    with pytest.raises(AppException) as exc_info:
        _validate_existing_adjustment(row, site_id=1, user_id=49, admin_id=7, delta=200, reason="补款")

    assert exc_info.value.status_code == 409


async def test_admin_credit_endpoint_forwards_idempotency_key_to_unified_wallet_service(monkeypatch):
    captured = {}

    async def fake_adjust_user_credit(db, **kwargs):
        captured.update(db=db, **kwargs)
        return CreditAdjustmentResult(user_id=49, delta=100, balance_before=0, balance_after=100)

    monkeypatch.setattr(admin_data, "adjust_user_credit", fake_adjust_user_credit)
    admin = SimpleNamespace(id=7, username="finance", site_id=1, system_super_admin=False)
    payload = admin_data.CreditAdjustmentRequest(delta=100, reason=" 后台补款 ", idempotency_key="request_123")
    response = await admin_data.credit_adjustment(49, payload, db="db-session", current_admin=admin)

    assert response.data == {
        "id": 49,
        "delta": 100,
        "amount": 100,
        "balance_before": 0,
        "balance_after": 100,
    }
    assert captured == {
        "db": "db-session",
        "user_id": 49,
        "delta": 100,
        "reason": "后台补款",
        "client_idempotency_key": "request_123",
        "admin": admin,
    }
