from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.routes import catalog, opencode
from app.core.exceptions import BusinessError
from app.models.agent import Sub2BalanceOperation, TeamMemberUsageLimit, UserAgentAccount, UserAgentApiKey
from app.services import sub2_image_billing as billing
from app.services.agent_openapi import AgentAPIError, AgentOpenAPIClient


def agent_config(**overrides):
    values = {
        "site_id": 7,
        "base_url": "https://sub2.example.test",
        "admin_api_key": "admin-key",
        "credit_to_agent_rate": Decimal("25"),
        "user_concurrency": 5,
        "user_rpm_limit": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_agent_models_can_sort_without_external_team_table_in_orm_metadata():
    assert UserAgentAccount.__mapper__._sorted_tables
    assert UserAgentApiKey.__mapper__._sorted_tables
    assert TeamMemberUsageLimit.__mapper__._sorted_tables


def test_fractional_charge_must_be_exactly_representable_upstream():
    assert billing._to_sub2_amount(Decimal("2.80"), agent_config(credit_to_agent_rate=100)) == Decimal("0.0280")
    with pytest.raises(BusinessError, match="无法精确结算"):
        billing._to_sub2_amount(Decimal("2.80"), agent_config(credit_to_agent_rate=3))


class FakeSession:
    def __init__(self, scalar_values=None):
        self.added = []
        self.scalar_values = list(scalar_values or [])
        self.rollback_count = 0
        self.commit_count = 0

    def add(self, value):
        self.added.append(value)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def rollback(self):
        self.rollback_count += 1

    async def commit(self):
        self.commit_count += 1


def test_agent_balance_change_uses_admin_endpoint_and_idempotency_key(monkeypatch):
    client = AgentOpenAPIClient(agent_config())
    captured = {}

    def fake_request(method, path, body=None, idempotency_key=None, bearer_token=None):
        captured.update(
            method=method,
            path=path,
            body=body,
            idempotency_key=idempotency_key,
            bearer_token=bearer_token,
        )
        return {"data": {"balance": "12.4"}}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.subtract_balance(
        agent_user_id=99,
        amount=Decimal("0.4000"),
        idempotency_key="image2-image-debit:IMG001",
        notes="image task",
    )

    assert result.balance == Decimal("12.4")
    assert captured == {
        "method": "POST",
        "path": "/api/v1/admin/users/99/balance",
        "body": {"balance": 0.4, "operation": "subtract", "notes": "image task"},
        "idempotency_key": "image2-image-debit:IMG001",
        "bearer_token": None,
    }


def test_agent_api_key_update_uses_verified_admin_contract(monkeypatch):
    client = AgentOpenAPIClient(agent_config())
    captured = {}

    def fake_request(method, path, body=None, idempotency_key=None, bearer_token=None):
        captured.update(method=method, path=path, body=body)
        return {
            "data": {
                "api_key": {
                    "id": 31,
                    "name": "text-key",
                    "quota": "100.0000",
                    "quota_used": "12.5000",
                    "status": "active",
                }
            }
        }

    monkeypatch.setattr(client, "_request", fake_request)

    key = client.update_api_key(31, quota=Decimal("100"))

    assert captured == {"method": "PUT", "path": "/api/v1/admin/api-keys/31", "body": {"quota": 100.0}}
    assert key.id == 31
    assert key.quota == Decimal("100.0000")
    assert key.quota_used == Decimal("12.5000")
    assert key.status == "active"


def test_user_key_create_forwards_verified_sub2_fields_and_bearer_token(monkeypatch):
    client = AgentOpenAPIClient(agent_config())
    captured = {}

    def fake_request(method, path, body=None, idempotency_key=None, bearer_token=None):
        captured.update(method=method, path=path, body=body, idempotency_key=idempotency_key, bearer_token=bearer_token)
        return {"data": {"id": 88, "key": "sk-live", "group_id": 2, "quota": "50", "status": "active"}}

    monkeypatch.setattr(client, "_request", fake_request)

    key = client.create_user_api_key(
        token="user-token",
        name="image2-u52-code",
        group_id=2,
        idempotency_key="create-88",
        quota=50.0,
        expires_in_days=30,
        rate_limit_5h=10.0,
    )

    assert key.id == 88
    assert captured == {
        "method": "POST",
        "path": "/api/v1/keys",
        "body": {
            "name": "image2-u52-code",
            "group_id": 2,
            "quota": 50.0,
            "expires_in_days": 30,
            "rate_limit_5h": 10.0,
        },
        "idempotency_key": "create-88",
        "bearer_token": "user-token",
    }


def test_user_key_update_and_delete_use_owner_token(monkeypatch):
    client = AgentOpenAPIClient(agent_config())
    calls = []

    def fake_request(method, path, body=None, idempotency_key=None, bearer_token=None):
        calls.append((method, path, body, bearer_token))
        return {"data": {"id": 88, "key": "sk-live", "status": "inactive"}}

    monkeypatch.setattr(client, "_request", fake_request)
    client.update_user_api_key(token="owner-token", key_id=88, payload={"status": "inactive"})
    client.delete_user_api_key(token="owner-token", key_id=88)

    assert calls == [
        ("PUT", "/api/v1/keys/88", {"status": "inactive"}, "owner-token"),
        ("DELETE", "/api/v1/keys/88", None, "owner-token"),
    ]


def test_allowed_groups_update_uses_the_agent_admin_contract(monkeypatch):
    client = AgentOpenAPIClient(agent_config())
    captured = {}

    def fake_request(method, path, body=None, idempotency_key=None, bearer_token=None):
        captured.update(method=method, path=path, body=body, idempotency_key=idempotency_key, bearer_token=bearer_token)
        return {"data": {"id": 34}}

    monkeypatch.setattr(client, "_request", fake_request)

    client.update_user_allowed_groups(agent_user_id=34, allowed_groups=[13, 2, 13])

    assert captured == {
        "method": "PUT",
        "path": "/api/v1/admin/users/34",
        "body": {"allowed_groups": [2, 13]},
        "idempotency_key": None,
        "bearer_token": None,
    }


def test_api_key_usage_summary_is_batched_and_parsed(monkeypatch):
    client = AgentOpenAPIClient(agent_config())
    calls = []

    def fake_request(method, path, body=None, idempotency_key=None, bearer_token=None):
        calls.append((method, path, body, bearer_token))
        return {
            "data": {
                "stats": {
                    str(key_id): {
                        "api_key_id": key_id,
                        "today_actual_cost": "0.1000",
                        "total_actual_cost": "0.2500",
                    }
                    for key_id in body["api_key_ids"]
                }
            }
        }

    monkeypatch.setattr(client, "_request", fake_request)

    usage = client.get_api_keys_usage(token="owner-token", api_key_ids=list(range(1, 102)))

    assert len(calls) == 2
    assert len(calls[0][2]["api_key_ids"]) == 100
    assert calls[1][2]["api_key_ids"] == [101]
    assert calls[0][3] == "owner-token"
    assert usage[101].today_actual_cost == Decimal("0.1000")
    assert usage[101].total_actual_cost == Decimal("0.2500")


def test_user_api_key_list_reads_every_page_and_deduplicates_ids(monkeypatch):
    client = AgentOpenAPIClient(agent_config())
    calls = []

    def fake_request(method, path, body=None, idempotency_key=None, bearer_token=None):
        calls.append((method, path, body, idempotency_key, bearer_token))
        page = 1 if "page=1&" in path else 2
        items = (
            [{"id": key_id, "key": f"sk-{key_id}", "status": "active"} for key_id in range(1, 101)]
            if page == 1
            else [
                {"id": 100, "key": "sk-100", "status": "active"},
                {"id": 111, "key": "sk-111", "name": "image2-u49-text", "group_id": 2, "status": "active"},
                {"id": 112, "key": "sk-112", "name": "image2-u49-image", "group_id": 13, "status": "active"},
            ]
        )
        return {
            "data": {
                "items": items,
                "total": 102,
                "page": page,
                "page_size": 100,
            }
        }

    monkeypatch.setattr(client, "_request", fake_request)

    keys = client.list_user_api_keys(74)

    assert [key.id for key in keys[-2:]] == [111, 112]
    assert len(keys) == 102
    assert calls == [
        ("GET", "/api/v1/admin/users/74/api-keys?page=1&page_size=100", None, None, None),
        ("GET", "/api/v1/admin/users/74/api-keys?page=2&page_size=100", None, None, None),
    ]


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1")])
def test_agent_balance_change_rejects_non_positive_amount(amount):
    client = AgentOpenAPIClient(agent_config())

    with pytest.raises(ValueError, match="greater than zero"):
        client.change_balance(
            agent_user_id=99,
            amount=amount,
            operation="subtract",
            notes="invalid",
            idempotency_key="invalid",
        )


def test_credit_conversion_uses_configured_rate_and_display_rounds_down():
    config = agent_config(credit_to_agent_rate=Decimal("25"))

    assert billing._to_sub2_amount(10, config) == Decimal("0.4000")
    assert billing._to_display_credits(Decimal("0.4399"), config) == Decimal("10.99")


def test_credit_conversion_rejects_amount_below_sub2_precision():
    with pytest.raises(BusinessError) as exc_info:
        billing._to_sub2_amount(1, agent_config(credit_to_agent_rate=Decimal("100000")))

    assert exc_info.value.code == 50389


async def test_image_debit_returns_none_when_unified_billing_is_disabled(monkeypatch):
    async def fake_context(_db, _user_id):
        return None

    monkeypatch.setattr(billing, "_billing_context", fake_context)
    db = FakeSession()

    receipt = await billing.debit_image_task_balance(db, user_id=12, task_no="IMG001", credit_amount=10)

    assert receipt is None
    assert db.added == []


async def test_image_debit_uses_converted_amount_and_records_snapshot(monkeypatch):
    config = agent_config()
    account = SimpleNamespace(agent_user_id=99)
    calls = []

    async def fake_context(_db, _user_id, **_kwargs):
        return billing._BillingContext(config=config, account=account)

    class FakeClient:
        def subtract_balance(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(billing, "_billing_context", fake_context)
    monkeypatch.setattr(billing, "AgentOpenAPIClient", lambda _config: FakeClient())
    db = FakeSession()

    receipt = await billing.debit_image_task_balance(db, user_id=12, task_no="IMG001", credit_amount=10)

    assert receipt is not None
    assert receipt.amount == Decimal("0.4000")
    assert calls == [
        {
            "agent_user_id": 99,
            "amount": Decimal("0.4000"),
            "idempotency_key": "image2-image-debit:IMG001",
            "notes": "image2 图片任务 IMG001",
        }
    ]
    assert len(db.added) == 1
    operation = db.added[0]
    assert isinstance(operation, Sub2BalanceOperation)
    assert operation.operation == "subtract"
    assert operation.amount == Decimal("0.4000")
    assert operation.idempotency_key == "image2-image-debit:IMG001"


async def test_image_debit_maps_sub2_failure_to_balance_error(monkeypatch):
    config = agent_config()
    account = SimpleNamespace(agent_user_id=99)

    async def fake_context(_db, _user_id):
        return billing._BillingContext(config=config, account=account)

    class FakeClient:
        def subtract_balance(self, **_kwargs):
            raise AgentAPIError("insufficient balance")

    monkeypatch.setattr(billing, "_billing_context", fake_context)
    monkeypatch.setattr(billing, "AgentOpenAPIClient", lambda _config: FakeClient())

    with pytest.raises(BusinessError) as exc_info:
        await billing.debit_image_task_balance(FakeSession(), user_id=12, task_no="IMG001", credit_amount=10)

    assert exc_info.value.code == 40281
    assert exc_info.value.status_code == 402
    assert exc_info.value.message == "余额不足或扣费失败"


async def test_image_refund_reuses_original_debit_amount_when_rate_changes(monkeypatch):
    receipt = billing.Sub2BalanceReceipt(
        site_id=7,
        user_id=12,
        agent_user_id=99,
        amount=Decimal("0.4000"),
        debit_idempotency_key="image2-image-debit:IMG001",
        refund_idempotency_key="image2-image-refund:IMG001",
        biz_id="IMG001",
    )
    calls = []

    class FakeClient:
        def add_balance(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(billing, "AgentOpenAPIClient", lambda _config: FakeClient())
    db = FakeSession([agent_config(credit_to_agent_rate=Decimal("100"))])

    refunded = await billing.refund_image_task_balance(db, task_no="IMG001", receipt=receipt)

    assert refunded is True
    assert calls[0]["amount"] == Decimal("0.4000")
    assert calls[0]["idempotency_key"] == "image2-image-refund:IMG001"
    assert db.added[0].biz_type == "image_task_refund"


async def test_image_refund_loads_persisted_debit_snapshot(monkeypatch):
    operation = SimpleNamespace(
        site_id=7,
        user_id=12,
        agent_user_id=99,
        amount=Decimal("0.4000"),
        idempotency_key="image2-image-debit:IMG001",
    )
    calls = []

    class FakeClient:
        def add_balance(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(billing, "AgentOpenAPIClient", lambda _config: FakeClient())
    db = FakeSession([operation, agent_config(credit_to_agent_rate=Decimal("100"))])

    refunded = await billing.refund_image_task_balance(db, task_no="IMG001")

    assert refunded is True
    assert calls[0]["amount"] == Decimal("0.4000")


async def test_recharge_adds_total_credits_with_order_idempotency(monkeypatch):
    config = agent_config()
    account = SimpleNamespace(agent_user_id=99)
    calls = []

    async def fake_context(_db, _user_id, **_kwargs):
        return billing._BillingContext(config=config, account=account)

    class FakeClient:
        def add_balance(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(billing, "_billing_context", fake_context)
    monkeypatch.setattr(billing, "AgentOpenAPIClient", lambda _config: FakeClient())
    db = FakeSession()

    credited = await billing.credit_recharge_balance(db, user_id=12, order_no="RC001", credit_amount=110)

    assert credited is True
    assert calls[0]["amount"] == Decimal("4.4000")
    assert calls[0]["idempotency_key"] == "image2-recharge:RC001"
    assert db.added[0].biz_type == "recharge"


async def test_signin_adds_authoritative_credits_with_daily_idempotency(monkeypatch):
    config = agent_config()
    account = SimpleNamespace(agent_user_id=99)
    calls = []

    async def fake_context(_db, _user_id):
        return billing._BillingContext(config=config, account=account)

    class FakeClient:
        def add_balance(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(balance=Decimal("1.4000"))

    monkeypatch.setattr(billing, "_billing_context", fake_context)
    monkeypatch.setattr(billing, "AgentOpenAPIClient", lambda _config: FakeClient())
    db = FakeSession()

    balance_after = await billing.credit_signin_balance(
        db,
        user_id=12,
        sign_date=date(2026, 7, 30),
        credit_amount=10,
    )

    assert balance_after == 35
    assert calls == [
        {
            "agent_user_id": 99,
            "amount": Decimal("0.4000"),
            "idempotency_key": "image2-signin:12:2026-07-30",
            "notes": "image2 每日签到 2026-07-30",
        }
    ]
    assert db.added[0].operation == "add"
    assert db.added[0].biz_type == "signin"
    assert db.added[0].biz_id == "signin:2026-07-30"
    assert db.added[0].idempotency_key == "image2-signin:12:2026-07-30"


async def test_recharge_context_does_not_require_image_billing_switch(monkeypatch):
    user = SimpleNamespace(id=12, site_id=7)
    config = agent_config(is_enabled=True, image_billing_enabled=False)
    account = SimpleNamespace(agent_user_id=99, status="active")

    async def fake_billing_team(_db, _user):
        return SimpleNamespace(id=7, owner_user_id=12)

    monkeypatch.setattr(billing, "get_agent_billing_team", fake_billing_team)

    assert await billing._billing_context(
        FakeSession([user, config, account]),
        12,
        require_image_billing=False,
    ) == billing._BillingContext(config=config, account=account)
    assert await billing._billing_context(FakeSession([user, config]), 12) is None


async def test_billing_context_uses_selected_team_owner_wallet(monkeypatch):
    user = SimpleNamespace(id=12, site_id=7)
    config = agent_config(is_enabled=True, image_billing_enabled=True)
    team_owner_account = SimpleNamespace(agent_user_id=701, status="active")

    async def fake_billing_team(_db, _user):
        return SimpleNamespace(id=28, owner_user_id=49)

    monkeypatch.setattr(billing, "get_agent_billing_team", fake_billing_team)

    context = await billing._billing_context(FakeSession([user, config, team_owner_account]), 12)

    assert context == billing._BillingContext(config=config, account=team_owner_account)


async def test_billing_context_falls_back_to_legacy_owner_wallet(monkeypatch):
    user = SimpleNamespace(id=12, site_id=7)
    config = agent_config(is_enabled=True, image_billing_enabled=True)
    legacy_owner_account = SimpleNamespace(agent_user_id=702, status="active", team_id=None)

    async def fake_billing_team(_db, _user):
        return SimpleNamespace(id=28, owner_user_id=49)

    monkeypatch.setattr(billing, "get_agent_billing_team", fake_billing_team)

    context = await billing._billing_context(FakeSession([user, config, None, legacy_owner_account]), 12)

    assert context == billing._BillingContext(config=config, account=legacy_owner_account)


async def test_authoritative_balance_is_read_from_sub2_and_converted_for_display(monkeypatch):
    config = agent_config()
    account = SimpleNamespace(agent_user_id=99)

    async def fake_context(_db, _user_id):
        return billing._BillingContext(config=config, account=account)

    class FakeClient:
        def get_user(self, agent_user_id):
            assert agent_user_id == 99
            return SimpleNamespace(balance=Decimal("0.4399"))

    monkeypatch.setattr(billing, "_billing_context", fake_context)
    monkeypatch.setattr(billing, "AgentOpenAPIClient", lambda _config: FakeClient())

    assert await billing.authoritative_credit_balance(FakeSession(), user_id=12) == Decimal("10.99")


async def test_catalog_external_wallet_does_not_reject_stale_local_balance(monkeypatch):
    receipt = billing.Sub2BalanceReceipt(
        site_id=7,
        user_id=12,
        agent_user_id=99,
        amount=Decimal("0.4000"),
        debit_idempotency_key="image2-image-debit:IMG001",
        refund_idempotency_key="image2-image-refund:IMG001",
        biz_id="IMG001",
    )
    account = SimpleNamespace(id=3, balance=0, gift_balance=0, total_consumed=0, version=1)

    async def fake_external_debit(_db, **_kwargs):
        return receipt

    async def fake_account(_db, _user_id):
        return account

    monkeypatch.setattr(catalog, "debit_image_task_balance", fake_external_debit)
    monkeypatch.setattr(catalog, "get_or_create_credit_account_for_update", fake_account)
    db = FakeSession()

    result = await catalog.debit_image_task_credits(db, 12, "IMG001", 10)

    assert result is receipt
    assert account.balance == -10
    assert account.total_consumed == 10
    assert db.added[0].idempotency_key == "image-task:debit:IMG001"


async def test_catalog_local_wallet_still_rejects_insufficient_balance_when_switch_is_off(monkeypatch):
    account = SimpleNamespace(id=3, balance=0, gift_balance=0, total_consumed=0, version=1)

    async def fake_external_debit(_db, **_kwargs):
        return None

    async def fake_account(_db, _user_id):
        return account

    monkeypatch.setattr(catalog, "debit_image_task_balance", fake_external_debit)
    monkeypatch.setattr(catalog, "get_or_create_credit_account_for_update", fake_account)

    with pytest.raises(BusinessError) as exc_info:
        await catalog.debit_image_task_credits(FakeSession(), 12, "IMG001", 10)

    assert exc_info.value.code == 40030


async def test_catalog_compensates_when_local_mirror_write_fails_after_external_debit(monkeypatch):
    receipt = billing.Sub2BalanceReceipt(7, 12, 99, Decimal("0.4"), "debit", "refund", "IMG001")
    compensated = []

    async def fake_external_debit(_db, **_kwargs):
        return receipt

    async def failing_account(_db, _user_id):
        raise RuntimeError("database write failed")

    async def fake_compensation(_db, receipts):
        compensated.extend(receipts)

    monkeypatch.setattr(catalog, "debit_image_task_balance", fake_external_debit)
    monkeypatch.setattr(catalog, "get_or_create_credit_account_for_update", failing_account)
    monkeypatch.setattr(catalog, "compensate_image_task_creation_debits", fake_compensation)

    with pytest.raises(RuntimeError, match="database write failed"):
        await catalog.debit_image_task_credits(FakeSession(), 12, "IMG001", 10)

    assert compensated == [receipt]


async def test_creation_failure_compensates_all_external_debits(monkeypatch):
    receipts = [
        billing.Sub2BalanceReceipt(7, 12, 99, Decimal("0.4"), f"debit-{index}", f"refund-{index}", f"IMG00{index}")
        for index in (1, 2)
    ]
    refunded = []

    async def fake_refund(_db, *, task_no, receipt):
        refunded.append((task_no, receipt.refund_idempotency_key))
        return True

    monkeypatch.setattr(catalog, "refund_image_task_balance", fake_refund)
    db = FakeSession()

    await catalog.compensate_image_task_creation_debits(db, receipts)

    assert db.rollback_count == 1
    assert db.commit_count == 2
    assert refunded == [("IMG002", "refund-2"), ("IMG001", "refund-1")]


def test_manual_transfer_routes_are_removed():
    transfer_routes = [
        route
        for route in opencode.router.routes
        if getattr(route, "path", "") == "/opencode/transfers"
    ]

    assert transfer_routes == []
