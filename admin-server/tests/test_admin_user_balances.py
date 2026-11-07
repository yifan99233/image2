import json
from decimal import Decimal
from types import SimpleNamespace

from app.api.endpoints.admin_data import managed_user_balance_lookup
from app.services import admin_user_balances
from app.services.admin_user_balances import UserBalanceLookup, resolve_user_credit_balances
from app.services.sub2_balance import Sub2BalanceError, Sub2BalanceTarget, get_sub2_balance


def target(agent_user_id: int = 74) -> Sub2BalanceTarget:
    return Sub2BalanceTarget(
        base_url="https://sub2.example.test",
        admin_api_key="admin-key",
        agent_user_id=agent_user_id,
        credit_to_agent_rate=Decimal("100"),
    )


def test_get_sub2_balance_uses_admin_user_contract(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"data": {"balance": "241.89189732"}}).encode()

    def fake_urlopen(request, timeout):
        captured.update(
            url=request.full_url,
            method=request.method,
            headers=dict(request.header_items()),
            timeout=timeout,
        )
        return FakeResponse()

    monkeypatch.setattr("app.services.sub2_balance.urllib.request.urlopen", fake_urlopen)

    balance = get_sub2_balance(target(), timeout_seconds=3)

    assert balance == Decimal("241.89189732")
    assert captured == {
        "url": "https://sub2.example.test/api/v1/admin/users/74",
        "method": "GET",
        "headers": {"X-api-key": "admin-key"},
        "timeout": 3,
    }


async def test_shared_wallet_is_fetched_once_and_reused_for_all_members(monkeypatch):
    calls = []

    def fake_get_sub2_balance(balance_target, *, timeout_seconds):
        calls.append((balance_target.agent_user_id, timeout_seconds))
        return Decimal("241.89189732")

    monkeypatch.setattr(admin_user_balances, "get_sub2_balance", fake_get_sub2_balance)
    shared_target = target()

    resolved = await resolve_user_credit_balances(
        [
            UserBalanceLookup(user_id=49, local_balance=99999, target=shared_target),
            UserBalanceLookup(user_id=52, local_balance=0, target=shared_target),
            UserBalanceLookup(user_id=77, local_balance=120),
        ]
    )

    assert calls == [(74, admin_user_balances.REMOTE_BALANCE_REQUEST_TIMEOUT_SECONDS)]
    assert resolved[49].balance == Decimal("24189.18")
    assert resolved[49].source == "authoritative"
    assert resolved[52].balance == Decimal("24189.18")
    assert resolved[52].source == "authoritative"
    assert resolved[77].balance == 120
    assert resolved[77].source == "local"


async def test_remote_failure_returns_explicit_local_fallback(monkeypatch):
    def fail_get_sub2_balance(*_args, **_kwargs):
        raise Sub2BalanceError("upstream unavailable")

    monkeypatch.setattr(admin_user_balances, "get_sub2_balance", fail_get_sub2_balance)

    resolved = await resolve_user_credit_balances(
        [UserBalanceLookup(user_id=49, local_balance=99999, target=target())]
    )

    assert resolved[49].balance == 99999
    assert resolved[49].source == "local_fallback"


def test_managed_user_balance_lookup_requires_complete_active_remote_account():
    active_row = SimpleNamespace(
        id=49,
        credit_balance=99999,
        agent_base_url="https://sub2.example.test",
        agent_admin_api_key="admin-key",
        credit_to_agent_rate=Decimal("100"),
        agent_billing_enabled=True,
        agent_account_status="active",
        agent_user_id=74,
    )
    inactive_row = SimpleNamespace(**{**active_row.__dict__, "agent_account_status": "failed"})

    active_lookup = managed_user_balance_lookup(active_row)
    inactive_lookup = managed_user_balance_lookup(inactive_row)

    assert active_lookup.target == target()
    assert inactive_lookup.target is None
    assert inactive_lookup.local_balance == 99999
