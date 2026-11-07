from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select, text

from app.db.session import AsyncSessionLocal
from app.models.agent import AgentConfig, UserAgentAccount, UserAgentApiKey
from app.models.user import User
from app.services import agent_provisioning
from app.services.agent_openapi import AgentAPIKey, AgentUser
from app.services.team_sharing import grant_team_entitlement, user_team_members_table


async def test_register_login_and_me(client):
    register_response = await client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "strong-pass-123"},
    )
    assert register_response.status_code == 200
    assert register_response.json()["code"] == 0
    assert register_response.json()["data"]["access_token"]
    assert register_response.json()["data"]["user"]["username"] == "alice"

    login_response = await client.post(
        "/auth/login",
        json={"username": "alice", "password": "strong-pass-123"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["data"]["access_token"]

    me_response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["data"]["email"] == "alice@example.com"


async def test_register_accepts_chinese_username_and_login_with_email(client):
    register_response = await client.post(
        "/auth/register",
        json={"username": "胖虎", "email": "panghu@example.com", "password": "strong-pass-123"},
    )
    assert register_response.status_code == 200
    assert register_response.json()["data"]["user"]["username"] == "胖虎"

    login_response = await client.post(
        "/auth/login",
        json={"username": "panghu@example.com", "password": "strong-pass-123"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["data"]["user"]["username"] == "胖虎"


async def test_duplicate_register_rejected(client):
    payload = {"username": "alice", "email": "alice@example.com", "password": "strong-pass-123"}
    assert (await client.post("/auth/register", json=payload)).status_code == 200

    response = await client.post("/auth/register", json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == 40001


async def test_duplicate_email_rejected_across_sites(client):
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO site_configs (id, site_key, site_name, frontend_url, is_default, is_enabled)
                VALUES
                    (101, 'auth-test-a', 'Auth Test A', 'https://auth-a.example.test', false, true),
                    (102, 'auth-test-b', 'Auth Test B', 'https://auth-b.example.test', false, true)
                ON CONFLICT (id) DO UPDATE SET
                    frontend_url = EXCLUDED.frontend_url,
                    is_default = false,
                    is_enabled = true
                """
            )
        )
        await session.commit()

    payload = {"username": "alice-a", "email": "shared-auth@example.com", "password": "strong-pass-123"}
    first_response = await client.post("/auth/register", json=payload, headers={"Origin": "https://auth-a.example.test"})
    assert first_response.status_code == 200

    second_response = await client.post(
        "/auth/register",
        json={**payload, "username": "alice-b"},
        headers={"Origin": "https://auth-b.example.test"},
    )

    assert second_response.status_code == 400
    assert second_response.json()["code"] == 40001


async def test_register_with_invite_code_records_inviter(client):
    inviter_response = await client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "strong-pass-123"},
    )
    inviter_id = inviter_response.json()["data"]["user"]["id"]

    response = await client.post(
        "/auth/register",
        json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "strong-pass-123",
            "invite_code": f"U{inviter_id}",
        },
    )

    assert response.status_code == 200
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == "bob"))
        assert user.invited_by_user_id == inviter_id


async def test_reward_invite_link_uses_opaque_path_and_records_inviter(client):
    inviter_response = await client.post(
        "/auth/register",
        json={"username": "opaque-inviter", "email": "opaque-inviter@example.com", "password": "strong-pass-123"},
    )
    inviter = inviter_response.json()["data"]["user"]
    token = inviter_response.json()["data"]["access_token"]

    config_response = await client.get(
        "/invite/reward-config",
        headers={"Authorization": f"Bearer {token}", "Origin": "https://magic.example.test"},
    )

    assert config_response.status_code == 200
    invite_url = config_response.json()["data"]["invite_url"]
    parsed_invite_url = urlparse(invite_url)
    assert parsed_invite_url.netloc == "magic.example.test"
    assert parsed_invite_url.query == ""
    assert parsed_invite_url.path.startswith("/r/")
    assert "invite_code" not in invite_url

    referral_token = parsed_invite_url.path.removeprefix("/r/")
    invitee_response = await client.post(
        "/auth/register",
        json={
            "username": "opaque-invitee",
            "email": "opaque-invitee@example.com",
            "password": "strong-pass-123",
            "referral_token": referral_token,
        },
    )

    assert invitee_response.status_code == 200
    async with AsyncSessionLocal() as session:
        invitee = await session.scalar(select(User).where(User.username == "opaque-invitee"))
        assert invitee.invited_by_user_id == inviter["id"]


async def test_reward_invite_does_not_join_inviter_team(client):
    inviter_response = await client.post(
        "/auth/register",
        json={"username": "reward-owner", "email": "reward-owner@example.com", "password": "strong-pass-123"},
    )
    inviter = inviter_response.json()["data"]["user"]
    team_response = await client.get(
        "/team",
        headers={"Authorization": f"Bearer {inviter_response.json()['data']['access_token']}"},
    )
    team_id = team_response.json()["data"]["id"]

    async with AsyncSessionLocal() as session:
        await grant_team_entitlement(
            session,
            site_id=1,
            owner_user_id=inviter["id"],
            seat_count=2,
            source="test",
            source_reference="reward-invite-separation",
        )
        await session.commit()

    response = await client.post(
        "/auth/register",
        json={
            "username": "reward-invitee",
            "email": "reward-invitee@example.com",
            "password": "strong-pass-123",
            "invite_code": f"U{inviter['id']}",
        },
    )

    assert response.status_code == 200
    async with AsyncSessionLocal() as session:
        invitee = await session.scalar(select(User).where(User.username == "reward-invitee"))
        role = await session.scalar(
            select(user_team_members_table.c.role).where(
                user_team_members_table.c.team_id == team_id,
                user_team_members_table.c.user_id == invitee.id,
            )
        )
        assert role is None
        assert invitee.active_team_id is None
        assert invitee.invited_by_user_id == inviter["id"]


async def test_register_with_team_invite_link_joins_team_and_uses_shared_team_wallet(client, monkeypatch):
    remote_users: list[int] = []
    remote_key_requests: list[dict] = []

    class FakeAgentClient:
        def __init__(self, _config):
            pass

        def user_email_exists(self, _email):
            return False

        def create_user(self, *, user_id, username, email, password, allowed_groups):
            del username, allowed_groups
            remote_users.append(user_id)
            return AgentUser(id=9001, balance=Decimal("0"), email=email, password=password)

        def login_user(self, *, email, password):
            assert email == "team-owner@example.com"
            assert password
            return "shared-wallet-token"

        def list_user_api_keys(self, agent_user_id):
            assert agent_user_id == 9001
            return []

        def create_user_api_key(self, **kwargs):
            remote_key_requests.append(kwargs)
            key_id = 9100 + len(remote_key_requests)
            return AgentAPIKey(
                id=key_id,
                key=f"sk-team-{key_id}",
                name=str(kwargs["name"]),
                group_id=kwargs.get("group_id"),
            )

    monkeypatch.setattr(agent_provisioning, "AgentOpenAPIClient", FakeAgentClient)
    owner_response = await client.post(
        "/auth/register",
        json={"username": "team-owner", "email": "team-owner@example.com", "password": "strong-pass-123"},
    )
    owner = owner_response.json()["data"]["user"]
    owner_token = owner_response.json()["data"]["access_token"]
    team_response = await client.get("/team", headers={"Authorization": f"Bearer {owner_token}"})
    team = team_response.json()["data"]

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("UPDATE site_configs SET frontend_url = 'https://user.example.test', is_enabled = true WHERE id = 1")
        )
        await grant_team_entitlement(
            session,
            site_id=1,
            owner_user_id=owner["id"],
            seat_count=2,
            source="test",
            source_reference="team-invite-link",
        )
        session.add(
            AgentConfig(
                site_id=1,
                is_enabled=True,
                base_url="https://agent.example.test",
                admin_api_key="test-admin-key",
                text_group_id=11,
                image_group_id=12,
            )
        )
        await session.commit()

    link_response = await client.post(
        "/team-console/invite-link",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert link_response.status_code == 200
    invite_url = link_response.json()["data"]["invite_url"]
    invite_query = parse_qs(urlparse(invite_url).query)
    assert "invite_code" not in invite_query
    team_invite_token = invite_query["team_invite_token"][0]

    preview_response = await client.get("/auth/team-invite", params={"token": team_invite_token})
    assert preview_response.status_code == 200
    assert preview_response.json()["data"]["team_name"] == team["name"]

    register_response = await client.post(
        "/auth/register",
        json={
            "username": "team-invitee",
            "email": "team-invitee@example.com",
            "password": "strong-pass-123",
            "team_invite_token": team_invite_token,
        },
    )

    assert register_response.status_code == 200
    async with AsyncSessionLocal() as session:
        invitee = await session.scalar(select(User).where(User.username == "team-invitee"))
        role = await session.scalar(
            select(user_team_members_table.c.role).where(
                user_team_members_table.c.team_id == team["id"],
                user_team_members_table.c.user_id == invitee.id,
            )
        )
        assert role == "member"
        assert invitee.active_team_id == team["id"]
        assert invitee.invited_by_user_id is None

        owner_agent_account = await session.scalar(
            select(UserAgentAccount).where(UserAgentAccount.user_id == owner["id"])
        )
        invitee_agent_account = await session.scalar(
            select(UserAgentAccount).where(UserAgentAccount.user_id == invitee.id)
        )
        invitee_keys = (
            await session.scalars(
                select(UserAgentApiKey).where(UserAgentApiKey.user_id == invitee.id).order_by(UserAgentApiKey.id)
            )
        ).all()
        assert owner_agent_account.team_id == team["id"]
        assert invitee_agent_account.team_id == team["id"]
        assert invitee_agent_account.agent_user_id == owner_agent_account.agent_user_id == 9001
        assert invitee_agent_account.agent_password is None
        assert len(invitee_keys) == 2
        assert all(key.team_id == team["id"] for key in invitee_keys)
        assert all(key.agent_user_id == owner_agent_account.agent_user_id for key in invitee_keys)
        assert all(key.user_id == invitee.id for key in invitee_keys)

    assert remote_users == [owner["id"]]
    assert len(remote_key_requests) == 2
    assert all(request["token"] == "shared-wallet-token" for request in remote_key_requests)
    assert all(f"team-{team['id']}-user-{register_response.json()['data']['user']['id']}" in request["idempotency_key"] for request in remote_key_requests)

    duplicate_response = await client.post(
        "/auth/register",
        json={
            "username": "team-invitee-again",
            "email": "team-invitee@example.com",
            "password": "strong-pass-123",
            "team_invite_token": team_invite_token,
        },
    )
    assert duplicate_response.status_code == 400
    assert duplicate_response.json()["code"] == 40001
    assert len(remote_key_requests) == 2

    full_team_response = await client.post(
        "/auth/register",
        json={
            "username": "team-over-capacity",
            "email": "team-over-capacity@example.com",
            "password": "strong-pass-123",
            "team_invite_token": team_invite_token,
        },
    )
    assert full_team_response.status_code == 409
    assert full_team_response.json()["code"] == 40974
    assert len(remote_key_requests) == 2

    async with AsyncSessionLocal() as session:
        duplicate_user = await session.scalar(select(User).where(User.username == "team-invitee-again"))
        over_capacity_user = await session.scalar(select(User).where(User.username == "team-over-capacity"))
        membership_count = await session.scalar(
            select(func.count())
            .select_from(user_team_members_table)
            .where(user_team_members_table.c.team_id == team["id"])
        )
        assert duplicate_user is None
        assert over_capacity_user is None
        assert membership_count == 2


async def test_register_with_invalid_team_invite_rolls_back_user(client):
    response = await client.post(
        "/auth/register",
        json={
            "username": "invalid-team-invitee",
            "email": "invalid-team-invitee@example.com",
            "password": "strong-pass-123",
            "team_invite_token": "invalid-team-token",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40078
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == "invalid-team-invitee@example.com"))
        assert user is None


async def test_register_rejects_combined_reward_and_team_invites(client):
    response = await client.post(
        "/auth/register",
        json={
            "username": "conflicting-invitee",
            "email": "conflicting-invitee@example.com",
            "password": "strong-pass-123",
            "invite_code": "U1",
            "team_invite_token": "not-a-team-token",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40008


async def test_register_with_invalid_invite_code_rejected(client):
    response = await client.post(
        "/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": "strong-pass-123", "invite_code": "U999"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40002


async def test_register_with_invalid_referral_token_rejected(client):
    response = await client.post(
        "/auth/register",
        json={
            "username": "invalid-referral-invitee",
            "email": "invalid-referral-invitee@example.com",
            "password": "strong-pass-123",
            "referral_token": "invalid-referral-token",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40002
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == "invalid-referral-invitee@example.com"))
        assert user is None


async def test_disabled_user_cannot_login(client):
    await client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "strong-pass-123"},
    )
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == "alice"))
        user.is_active = False
        await session.commit()

    response = await client.post("/auth/login", json={"username": "alice", "password": "strong-pass-123"})

    assert response.status_code == 401
    assert response.json()["code"] == 40103


async def test_invalid_token_returns_401(client):
    response = await client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401
