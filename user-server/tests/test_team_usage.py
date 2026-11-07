from decimal import Decimal

import pytest

from app.core.exceptions import BusinessError
from app.api.routes import team_console
from app.services.agent_openapi import AgentAPIError, AgentAPIKey, AgentAPIKeyUsage
from app.services.team_usage import _aggregate_keys, _apply_quota_updates, _find_bound_key, _quota_assignments, _quota_out, _usage_payload, normalize_quota


def api_key(key_id: int, quota: str, used: str = "0") -> AgentAPIKey:
    return AgentAPIKey(id=key_id, key="", quota=Decimal(quota), quota_used=Decimal(used), status="active")


def test_bound_keys_are_resolved_by_persisted_ids_not_list_order():
    keys = [api_key(22, "50"), api_key(11, "100")]

    assert _find_bound_key(keys, 11, "Token").quota == Decimal("100")
    assert _find_bound_key(keys, 22, "图片/视频").quota == Decimal("50")

    with pytest.raises(AgentAPIError):
        _find_bound_key(keys, 99, "Token")


def test_zero_quota_is_reported_as_unlimited():
    result = _quota_out(api_key(11, "0", "12.5"))

    assert result["unlimited"] is True
    assert result["remaining"] is None
    assert result["used"] == 12.5


def test_member_usage_payload_does_not_expose_shared_balance_by_default():
    row = type("MemberRow", (), {
        "membership_id": 7,
        "user_id": 9,
        "username": "member",
        "nickname": None,
        "email": "member@example.com",
        "avatar_url": None,
        "role": "member",
    })()

    payload = _usage_payload(row, Decimal("88.5"), api_key(11, "10"), api_key(22, "20"))

    assert "balance" not in payload
    manager_payload = _usage_payload(
        row,
        Decimal("88.5"),
        api_key(11, "10"),
        api_key(22, "20"),
        include_balance=True,
    )
    assert manager_payload["balance"] == 88.5


def test_quota_is_rounded_to_sub2_precision_and_rejects_negative_values():
    assert normalize_quota(Decimal("12.34567")) == Decimal("12.3457")
    with pytest.raises(BusinessError):
        normalize_quota(Decimal("-0.0001"))


def test_member_quota_is_distributed_across_multiple_keys_without_resetting_usage():
    first = api_key(11, "100", "40")
    second = api_key(22, "50", "10")

    assignments = _quota_assignments([first, second], Decimal("120"))

    assert sum(assignments.values(), Decimal("0")) == Decimal("120")
    assert assignments[11] >= first.quota_used
    assert assignments[22] >= second.quota_used


def test_unlimited_member_quota_sets_every_key_to_unlimited():
    assignments = _quota_assignments([api_key(11, "100"), api_key(22, "50")], Decimal("0"))

    assert assignments == {11: Decimal("0"), 22: Decimal("0")}


def test_team_usage_aggregates_real_cost_from_current_and_historical_keys():
    aggregated = _aggregate_keys(
        [api_key(116, "100")],
        [116],
        [115, 116],
        {
            115: AgentAPIKeyUsage(api_key_id=115, total_actual_cost=Decimal("0.000965")),
            116: AgentAPIKeyUsage(api_key_id=116, total_actual_cost=Decimal("0.06247476")),
        },
        "Token",
        Decimal("100"),
    )

    assert aggregated.quota == Decimal("100")
    assert aggregated.quota_used == Decimal("0.06343976")


async def test_second_quota_update_failure_restores_first_key():
    calls: list[tuple[int, Decimal]] = []

    class FakeClient:
        def update_api_key(self, key_id: int, *, quota: Decimal):
            calls.append((key_id, quota))
            if key_id == 22 and quota == Decimal("60"):
                raise AgentAPIError("image key update failed")
            return api_key(key_id, str(quota))

    with pytest.raises(BusinessError) as exc_info:
        await _apply_quota_updates(
            FakeClient(),
            text_key=api_key(11, "100"),
            image_key=api_key(22, "50"),
            text_quota=Decimal("120"),
            image_quota=Decimal("60"),
        )

    assert exc_info.value.message == "额度更新失败，已恢复原额度"
    assert calls == [(11, Decimal("120")), (22, Decimal("60")), (11, Decimal("100"))]


async def test_member_permission_is_self_only_at_route_boundary(monkeypatch):
    async def fake_access(_db, _user):
        return {"current_role": "member"}

    monkeypatch.setattr(team_console, "require_team_console_access", fake_access)

    await team_console.require_team_console_permission(object(), object(), "usage:self:view")
    with pytest.raises(BusinessError) as exc_info:
        await team_console.require_team_console_permission(object(), object(), "usage:view")

    assert exc_info.value.status_code == 403
