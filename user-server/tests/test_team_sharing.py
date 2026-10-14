from types import SimpleNamespace

import pytest

from app.core.exceptions import BusinessError
from app.services.team_sharing import (
    TEAM_COLLABORATION_MIN_SEATS,
    TeamEntitlementSummary,
    can_assign_team_member_role,
    can_manage_team_members,
    can_remove_team_member,
    normalize_member_role,
    select_agent_billing_team,
    team_console_permissions,
)


def test_team_member_role_normalization_is_restricted():
    assert normalize_member_role(None) == "member"
    assert normalize_member_role(" ADMIN ") == "admin"
    with pytest.raises(BusinessError):
        normalize_member_role("owner")


def test_team_member_management_roles_are_deliberate():
    assert can_manage_team_members("owner")
    assert can_manage_team_members("admin")
    assert not can_manage_team_members("member")

    assert can_assign_team_member_role("owner", "admin")
    assert can_assign_team_member_role("admin", "member")
    assert not can_assign_team_member_role("admin", "admin")

    assert can_remove_team_member("owner", "admin")
    assert can_remove_team_member("admin", "member")
    assert not can_remove_team_member("admin", "admin")
    assert not can_remove_team_member("owner", "owner")


def test_team_collaboration_requires_paid_capacity():
    assert not TeamEntitlementSummary(seat_limit=TEAM_COLLABORATION_MIN_SEATS - 1).collaboration_enabled
    assert TeamEntitlementSummary(seat_limit=TEAM_COLLABORATION_MIN_SEATS).collaboration_enabled


def test_team_console_permissions_allow_self_usage_without_team_visibility():
    member_permissions = team_console_permissions("member")
    admin_permissions = team_console_permissions("admin")

    assert "usage:self:view" in member_permissions
    assert "budgets:self:view" in member_permissions
    assert "members:view" not in member_permissions
    assert "usage:view" not in member_permissions
    assert "budgets:manage" in admin_permissions


def test_agent_billing_defaults_to_single_external_team_when_no_selection():
    organization = SimpleNamespace(id=28, owner_user_id=49)

    selected = select_agent_billing_team(52, None, [organization])

    assert selected.id == 28


def test_agent_billing_honors_personal_workspace_selection():
    personal = SimpleNamespace(id=31, owner_user_id=52)
    organization = SimpleNamespace(id=28, owner_user_id=49)

    selected = select_agent_billing_team(52, personal, [organization])

    assert selected.id == 31


def test_agent_billing_keeps_selected_external_team():
    selected_team = SimpleNamespace(id=28, owner_user_id=49)
    other_team = SimpleNamespace(id=30, owner_user_id=60)

    selected = select_agent_billing_team(52, selected_team, [selected_team, other_team])

    assert selected.id == 28


def test_agent_billing_requires_selection_when_multiple_external_teams_exist():
    external = [SimpleNamespace(id=28, owner_user_id=49), SimpleNamespace(id=30, owner_user_id=60)]

    with pytest.raises(BusinessError) as exc_info:
        select_agent_billing_team(52, None, external)

    assert exc_info.value.code == 40978
