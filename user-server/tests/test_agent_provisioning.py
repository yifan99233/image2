import io
import urllib.error
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import agent_provisioning
from app.api.routes.opencode import _mark_key_deleted
from app.models.agent import UserAgentAccount, UserAgentApiKey
from app.services.agent_openapi import AgentAPIError, AgentAPIKey, AgentOpenAPIClient, AgentUser
from app.services.agent_provisioning import (
    AGENT_ACCOUNT_ALIAS_DOMAIN,
    _LegacyAccount,
    _account_row,
    _agent_email_conflict,
    _configured_group_ids,
    _create_wallet_user,
    _default_key_idempotency_key,
    _delete_legacy_keys,
    _ensure_deferred_legacy_credentials,
    _ensure_default_key,
    _generated_agent_identity,
    _legacy_key_create_options,
    _remaining_quota,
    _sync_configured_allowed_groups,
    agent_account_requires_sync,
    sync_agent_account,
)


def test_agent_email_lookup_uses_exact_match_after_remote_search():
    client = object.__new__(AgentOpenAPIClient)
    requested_paths = []

    def fake_request(method, path):
        requested_paths.append((method, path))
        return {
            "data": {
                "items": [
                    {"id": 1, "email": "prefix-owner@example.test"},
                    {"id": 2, "email": "OWNER@EXAMPLE.TEST"},
                ]
            }
        }

    client._request = fake_request

    assert client.user_email_exists("owner@example.test")
    assert requested_paths[0][0] == "GET"
    assert "search=owner%40example.test" in requested_paths[0][1]


def test_agent_http_conflict_preserves_machine_readable_reason(monkeypatch):
    client = AgentOpenAPIClient(
        SimpleNamespace(
            base_url="https://sub2.example.test",
            admin_api_key="admin-key",
            user_concurrency=5,
            user_rpm_limit=0,
        )
    )
    body = io.BytesIO(b'{"code":409,"message":"email already exists","reason":"EMAIL_EXISTS"}')

    def fake_urlopen(_request, timeout):
        assert timeout == 20
        raise urllib.error.HTTPError(
            "https://sub2.example.test/api/v1/admin/users",
            409,
            "Conflict",
            {},
            body,
        )

    monkeypatch.setattr("app.services.agent_openapi.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(AgentAPIError) as exc_info:
        client.create_user(
            user_id=58,
            username="owner",
            email="owner@example.test",
            password="generated-password",
            allowed_groups=[],
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.reason == "EMAIL_EXISTS"
    assert _agent_email_conflict(exc_info.value)


def test_generated_agent_identity_is_traceable_to_image2_user(monkeypatch):
    monkeypatch.setattr(agent_provisioning.secrets, "token_hex", lambda _length: "a1b2c3d4e5f6")

    username, email = _generated_agent_identity(58)

    assert username == "image2-u58-a1b2c3d4e5f6"
    assert email == f"{username}@{AGENT_ACCOUNT_ALIAS_DOMAIN}"


async def test_existing_sub2_email_creates_random_alias_and_returns_actual_mapping(monkeypatch):
    owner = SimpleNamespace(
        id=58,
        site_id=4,
        username="owner",
        email="owner@example.test",
    )

    class FakeClient:
        def __init__(self):
            self.created = []

        def user_email_exists(self, email):
            assert email == owner.email
            return True

        def create_user(self, **kwargs):
            self.created.append(kwargs)
            return AgentUser(
                id=901,
                balance=Decimal("0"),
                email=kwargs["email"],
                password=kwargs["password"],
            )

    monkeypatch.setattr(agent_provisioning.secrets, "token_hex", lambda _length: "a1b2c3d4e5f6")
    client = FakeClient()

    result = await _create_wallet_user(
        client=client,
        owner=owner,
        password="generated-password",
        allowed_groups=[2, 13],
    )

    assert result.id == 901
    assert result.email == "image2-u58-a1b2c3d4e5f6@users.image2.invalid"
    assert client.created == [
        {
            "user_id": 58,
            "username": "image2-u58-a1b2c3d4e5f6",
            "email": result.email,
            "password": "generated-password",
            "allowed_groups": [2, 13],
        }
    ]


async def test_create_race_retries_with_new_alias_on_structured_email_conflict(monkeypatch):
    owner = SimpleNamespace(
        id=58,
        site_id=4,
        username="owner",
        email="owner@example.test",
    )

    class FakeClient:
        def __init__(self):
            self.created = []

        def user_email_exists(self, _email):
            return False

        def create_user(self, **kwargs):
            self.created.append(kwargs)
            if len(self.created) == 1:
                raise AgentAPIError("email already exists", status_code=409, reason="EMAIL_EXISTS")
            return AgentUser(
                id=902,
                balance=Decimal("0"),
                email=kwargs["email"],
                password=kwargs["password"],
            )

    monkeypatch.setattr(agent_provisioning.secrets, "token_hex", lambda _length: "race12345678")
    client = FakeClient()

    result = await _create_wallet_user(
        client=client,
        owner=owner,
        password="generated-password",
        allowed_groups=[],
    )

    assert client.created[0]["email"] == owner.email
    assert client.created[1]["email"] == "image2-u58-race12345678@users.image2.invalid"
    assert result.email == client.created[1]["email"]
    assert _agent_email_conflict(AgentAPIError("email already exists", status_code=409))
    assert not _agent_email_conflict(AgentAPIError("upstream unavailable", status_code=503))


async def test_configured_fixed_groups_are_synced_before_default_key_repair():
    class FakeClient:
        def __init__(self):
            self.updated = []

        def update_user_allowed_groups(self, **kwargs):
            self.updated.append(kwargs)

    client = FakeClient()
    config = SimpleNamespace(text_group_id=2, image_group_id=13)

    await _sync_configured_allowed_groups(client, agent_user_id=76, config=config)

    assert _configured_group_ids(config) == [2, 13]
    assert client.updated == [{"agent_user_id": 76, "allowed_groups": [2, 13]}]


def test_deleting_default_key_preserves_replacement_anchor():
    account = UserAgentAccount(
        text_api_key_id=124,
        text_api_key="sk-text",
        image_api_key_id=125,
        image_api_key="sk-image",
    )
    mapping = UserAgentApiKey(agent_key_id=125, is_deleted=False)

    _mark_key_deleted(account, mapping)

    assert mapping.is_deleted is True
    assert account.image_api_key is None
    assert account.image_api_key_id == 125
    assert account.text_api_key == "sk-text"
    assert account.text_api_key_id == 124


def test_default_key_idempotency_is_bound_to_config_group_and_replacement_generation():
    original = _default_key_idempotency_key(
        team_id=35,
        user_id=58,
        kind="image",
        group_id=5,
        replacement_key_id=None,
    )
    replacement = _default_key_idempotency_key(
        team_id=35,
        user_id=58,
        kind="image",
        group_id=13,
        replacement_key_id=125,
    )

    assert original == "image2-agent-team-35-user-58-image-group-5-initial"
    assert replacement == "image2-agent-team-35-user-58-image-group-13-after-125"
    assert replacement != original


async def test_deleted_default_key_is_recreated_in_the_current_config_group():
    previous_mapping = SimpleNamespace(agent_key_id=125)

    class FakeDB:
        def __init__(self):
            self.scalar_results = [previous_mapping, None]
            self.added = []

        async def scalar(self, _query):
            return self.scalar_results.pop(0)

        def add(self, value):
            self.added.append(value)

    class FakeClient:
        def __init__(self):
            self.created = []

        def create_user_api_key(self, **kwargs):
            self.created.append(kwargs)
            return AgentAPIKey(id=201, key="sk-new", name=kwargs["name"], group_id=kwargs["group_id"], status="active")

    db = FakeDB()
    client = FakeClient()
    account = SimpleNamespace(agent_user_id=76, text_api_key_id=None, image_api_key_id=None)
    user = SimpleNamespace(id=58, site_id=1)

    key = await _ensure_default_key(
        db,
        client=client,
        token="owner-token",
        account=account,
        user=user,
        team_id=35,
        group_id=13,
        kind="image",
        display_name="图片 / 视频 Key",
        existing_keys=[],
    )

    assert key.id == 201
    assert client.created == [
        {
            "token": "owner-token",
            "name": "image2-u58-image",
            "group_id": 13,
            "idempotency_key": "image2-agent-team-35-user-58-image-group-13-after-125",
        }
    ]
    assert len(db.added) == 1
    assert db.added[0].group_id == 13


async def test_existing_account_keeps_wallet_team_until_migration_succeeds():
    account = UserAgentAccount(
        user_id=58,
        team_id=31,
        agent_email="member@example.test",
        agent_user_id=73,
        status="active",
    )

    class FakeDB:
        async def scalar(self, _query):
            return account

        def add(self, _value):
            raise AssertionError("existing account must not be added again")

        async def flush(self):
            raise AssertionError("existing account does not require a flush")

    result = await _account_row(
        FakeDB(),
        SimpleNamespace(id=58, email="member@example.test"),
        team_id=28,
    )

    assert result.team_id == 31


async def test_positive_legacy_balance_preserves_user_access_and_retries_team_migration(monkeypatch):
    config = SimpleNamespace(
        site_id=1,
        is_enabled=True,
        text_group_id=2,
        image_group_id=13,
    )
    team = SimpleNamespace(id=28, owner_user_id=49)
    owner = SimpleNamespace(
        id=49,
        site_id=1,
        username="owner",
        email="owner@example.test",
    )
    user = SimpleNamespace(
        id=58,
        site_id=1,
        username="member",
        email="member@example.test",
    )
    member_account = UserAgentAccount(
        user_id=58,
        team_id=28,
        agent_user_id=73,
        agent_email="member@example.test",
        agent_password="legacy-password",
        text_api_key_id=109,
        text_api_key="legacy-text-key",
        image_api_key_id=110,
        image_api_key="legacy-image-key",
        status="failed",
        failure_message="旧版独立账户仍有余额，需要管理员完成团队钱包迁移",
    )
    wallet = UserAgentAccount(
        user_id=49,
        team_id=28,
        agent_user_id=74,
        agent_email="owner@example.test",
        agent_password="wallet-password",
        status="active",
    )

    class FakeDB:
        def __init__(self):
            self.scalar_results = [config, owner, member_account, wallet, 31]

        async def scalar(self, _query):
            return self.scalar_results.pop(0)

        def add(self, _value):
            raise AssertionError("all account rows already exist")

        async def flush(self):
            raise AssertionError("deferred migration must not replace account bindings")

    class FakeClient:
        def __init__(self, _config):
            pass

        def get_user(self, agent_user_id):
            assert agent_user_id == 73
            return AgentUser(
                id=73,
                balance=Decimal("12.5"),
                email="member@example.test",
                password="",
            )

    async def fake_billing_team(_db, current_user):
        assert current_user is user
        return team

    monkeypatch.setattr(agent_provisioning, "AgentOpenAPIClient", FakeClient)
    monkeypatch.setattr(agent_provisioning, "get_agent_billing_team", fake_billing_team)

    result = await sync_agent_account(FakeDB(), user)

    assert result is member_account
    assert result.status == "active"
    assert result.failure_message is None
    assert result.team_id == 31
    assert result.agent_user_id == 73
    assert result.text_api_key == "legacy-text-key"
    assert result.image_api_key == "legacy-image-key"
    assert agent_account_requires_sync(result, billing_team_id=28)


async def test_funded_legacy_account_repairs_missing_server_credentials(monkeypatch):
    account = UserAgentAccount(
        user_id=58,
        agent_user_id=73,
        agent_email="member@example.test",
        agent_password=None,
        status="active",
    )
    config = SimpleNamespace(text_group_id=2, image_group_id=13)

    class FakeClient:
        def __init__(self):
            self.reset_calls = []

        def reset_user_password(self, **kwargs):
            self.reset_calls.append(kwargs)
            return AgentUser(
                id=kwargs["agent_user_id"],
                balance=Decimal("12.5"),
                email="member@example.test",
                password=kwargs["password"],
            )

    client = FakeClient()
    monkeypatch.setattr(agent_provisioning.secrets, "token_urlsafe", lambda _length: "server-generated-password")

    await _ensure_deferred_legacy_credentials(
        client=client,
        config=config,
        account=account,
    )

    assert account.agent_password == "server-generated-password"
    assert client.reset_calls == [
        {
            "agent_user_id": 73,
            "password": "server-generated-password",
            "allowed_groups": [2, 13],
        }
    ]


def test_legacy_key_migration_preserves_remaining_limits():
    key = AgentAPIKey(
        id=114,
        key="sk-old",
        group_id=2,
        quota=Decimal("100"),
        quota_used=Decimal("25"),
        rate_limit_5h=Decimal("10"),
        rate_limit_1d=Decimal("30"),
        rate_limit_7d=Decimal("100"),
        ip_whitelist=("1.2.3.4",),
        ip_blacklist=("5.6.7.8",),
    )

    assert _remaining_quota(key) == Decimal("75")
    assert _legacy_key_create_options(key) == {
        "quota": 75.0,
        "rate_limit_5h": 10.0,
        "rate_limit_1d": 30.0,
        "rate_limit_7d": 100.0,
        "ip_whitelist": ["1.2.3.4"],
        "ip_blacklist": ["5.6.7.8"],
    }


def test_unlimited_legacy_key_remains_unlimited():
    key = AgentAPIKey(id=114, key="sk-old", quota=Decimal("0"), quota_used=Decimal("0"))

    assert _remaining_quota(key) == Decimal("0")


def test_missing_or_keyless_account_requires_team_wallet_initialization():
    keyless = SimpleNamespace(
        status="active",
        agent_user_id=74,
        team_id=28,
        text_api_key=None,
        image_api_key=None,
    )

    assert agent_account_requires_sync(None, 28)
    assert agent_account_requires_sync(keyless, 28)


def test_account_bound_to_personal_wallet_requires_team_wallet_migration():
    personal = SimpleNamespace(
        status="active",
        agent_user_id=73,
        team_id=31,
        text_api_key="text-key",
        image_api_key="image-key",
    )
    shared = SimpleNamespace(
        status="active",
        agent_user_id=74,
        team_id=28,
        text_api_key="text-key",
        image_api_key="image-key",
    )

    assert agent_account_requires_sync(personal, 28)
    assert not agent_account_requires_sync(shared, 28)


async def test_legacy_key_cleanup_calls_delete_api_and_marks_mappings_deleted():
    mappings = [SimpleNamespace(agent_key_id=109, is_deleted=False), SimpleNamespace(agent_key_id=114, is_deleted=False)]
    legacy = _LegacyAccount(
        default_key_ids=frozenset({109}),
        mappings=tuple(mappings),
        live_keys=(AgentAPIKey(id=109, key="sk-default"), AgentAPIKey(id=114, key="sk-custom")),
        token="legacy-token",
    )

    class FakeClient:
        def __init__(self):
            self.deleted = []

        def delete_user_api_key(self, *, token: str, key_id: int) -> None:
            self.deleted.append((token, key_id))

    client = FakeClient()

    await _delete_legacy_keys(client=client, legacy=legacy)

    assert client.deleted == [("legacy-token", 109), ("legacy-token", 114)]
    assert all(mapping.is_deleted for mapping in mappings)


@pytest.mark.parametrize("text_group,error,expected", [
    (2, AgentAPIError("agent 接口返回 404: group not found", status_code=404), "active"),
    (None, None, "active"),
    (2, None, "active"),
    (2, AgentAPIError("unauthorized", status_code=401), "failed"),
    (2, AgentAPIError("timed out"), "failed"),
    (2, AgentAPIError("route not found", status_code=404), "failed"),
])
async def test_optional_text_key_does_not_block_image_initialization(monkeypatch, text_group, error, expected):
    config = SimpleNamespace(is_enabled=True, text_group_id=text_group, image_group_id=36)
    user = SimpleNamespace(id=58, site_id=1)
    account = UserAgentAccount(user_id=58, team_id=28, agent_user_id=74,
                               agent_email="test@example.test", agent_password="password", status="failed")
    class DB:
        def __init__(self):
            self.values = iter([config, user, 0])
        async def scalar(self, query):
            return next(self.values)
        async def flush(self):
            pass
    class Client:
        def login_user(self, **kwargs):
            return "token"
        def list_user_api_keys(self, user_id):
            return []
    async def account_row(*args, **kwargs):
        return account
    async def billing(*args, **kwargs):
        return SimpleNamespace(id=28, owner_user_id=58)
    async def noop(*args, **kwargs):
        pass
    calls = []
    async def key(*args, **kwargs):
        calls.append(kwargs["kind"])
        if kwargs["kind"] == "text" and error:
            raise error
        return AgentAPIKey(id=101 if kwargs["kind"] == "text" else 102, key=kwargs["kind"])
    monkeypatch.setattr(agent_provisioning, "AgentOpenAPIClient", lambda config: Client())
    monkeypatch.setattr(agent_provisioning, "get_agent_billing_team", billing)
    monkeypatch.setattr(agent_provisioning, "_account_row", account_row)
    monkeypatch.setattr(agent_provisioning, "_ensure_wallet", account_row)
    for name in ("_legacy_account", "_sync_configured_allowed_groups", "_migrate_legacy_custom_keys", "_delete_legacy_keys"):
        monkeypatch.setattr(agent_provisioning, name, noop)
    monkeypatch.setattr(agent_provisioning, "_ensure_default_key", key)
    result = await sync_agent_account(DB(), user)
    assert result.status == expected
    if expected == "active":
        assert result.image_api_key == "image"
        assert result.text_api_key == ("text" if text_group and not error else None)
        assert not agent_account_requires_sync(result, 28)
        assert calls[-1] == "image"
    else:
        assert calls == ["text"]
        assert result.failure_message == str(error)


async def test_opencode_login_accepts_image_only_account(monkeypatch):
    from app.api.routes import opencode
    from app.schemas.auth import LoginRequest
    account = UserAgentAccount(status="active", agent_user_id=74, team_id=28, image_api_key="image")
    async def yes(*args):
        return True
    async def site(*args):
        return 1
    async def user(*args):
        return SimpleNamespace(id=58, site_id=1)
    async def config(*args):
        return SimpleNamespace()
    async def team(*args):
        return SimpleNamespace(id=28)
    class DB:
        async def scalar(self, query):
            return account
    monkeypatch.setattr(opencode, "login_rate_limit_key", yes)
    monkeypatch.setattr(opencode, "current_site_id", site)
    monkeypatch.setattr(opencode, "authenticate_user_for_opencode", user)
    monkeypatch.setattr(opencode, "get_config", config)
    monkeypatch.setattr(opencode, "get_agent_billing_team", team)
    result = await opencode.opencode_login(LoginRequest(username="alice", password="password"),
                                           SimpleNamespace(client=None), DB())
    assert result.data.status == "active"
    assert result.data.text_api_key is None
    assert result.data.image_api_key == "image"
