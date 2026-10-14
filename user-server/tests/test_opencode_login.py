from decimal import Decimal

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.agent import AgentConfig, UserAgentAccount, UserAgentApiKey
from app.models.openagent_release import OpenAgentRelease
from app.models.user import User
from app.api.routes.opencode import _key_out, agent_account_out
from app.services.agent_openapi import AgentAPIKey, AgentAPIKeyUsage, AgentOpenAPIClient
from app.services.team_sharing import get_or_create_user_team


def test_agent_account_output_exposes_gateway_base_url_but_not_internal_agent_url_or_admin_key():
    config = AgentConfig(
        base_url="https://agent.example.test/",
        admin_api_key="must-not-leak",
        credit_to_agent_rate=100,
        image_billing_enabled=False,
    )
    account = UserAgentAccount(
        agent_email="member@example.com",
        status="active",
        text_api_key="text-key",
        image_api_key="image-key",
    )

    output = agent_account_out(
        account,
        config,
        api_base_url="https://magic.example.test",
    )

    assert output["api_base_url"] == "https://magic.example.test"
    assert "agent.example.test" not in str(output)
    assert "admin_api_key" not in output


def test_key_output_uses_authoritative_usage_dashboard_costs():
    mapping = UserAgentApiKey(
        id=72,
        site_id=4,
        team_id=28,
        user_id=77,
        agent_user_id=74,
        agent_key_id=150,
        api_key="sk-test",
        name="Token Key",
        group_id=2,
    )
    key = AgentAPIKey(
        id=150,
        key="sk-test",
        group_id=2,
        quota=Decimal("2"),
        quota_used=Decimal("0"),
        today_actual_cost=Decimal("0"),
        total_actual_cost=Decimal("0"),
        created_at="2026-07-26T09:10:31+08:00",
    )
    usage = AgentAPIKeyUsage(
        api_key_id=150,
        today_actual_cost=Decimal("0.125"),
        total_actual_cost=Decimal("7.2106837"),
    )

    output = _key_out(mapping, key, {2: {"id": 2, "name": "Agent", "platform": "openai"}}, usage)

    assert output["quota_used"] == 7.2106837
    assert output["today_actual_cost"] == 0.125
    assert output["total_actual_cost"] == 7.2106837


async def _register_user(client) -> tuple[int, str]:
    response = await client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "strong-pass-123"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    return data["user"]["id"], data["access_token"]


async def _enable_opencode_with_keys(user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        team = await get_or_create_user_team(session, user)
        session.add(
            AgentConfig(
                id=1,
                is_enabled=True,
                base_url="https://agent.example.test",
                admin_api_key="admin-key",
                credit_to_agent_rate=1,
            )
        )
        session.add(
            UserAgentAccount(
                user_id=user_id,
                team_id=int(team.id),
                agent_user_id=1001,
                agent_email=user.email,
                text_api_key_id=11,
                text_api_key="text-key-123",
                image_api_key="image-key-456",
                status="active",
            )
        )
        await session.commit()


async def test_opencode_login_returns_keys_without_replacing_image2_token(client):
    user_id, image2_token = await _register_user(client)
    await _enable_opencode_with_keys(user_id)

    response = await client.post(
        "/opencode/login",
        json={"username": "alice", "password": "strong-pass-123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "OpenAgent 登录成功"
    assert payload["data"] == {
        "status": "active",
        "agent_user_id": 1001,
        "text_api_key": "text-key-123",
        "image_api_key": "image-key-456",
    }
    assert "access_token" not in payload["data"]

    me_response = await client.get("/auth/me", headers={"Authorization": f"Bearer {image2_token}"})
    assert me_response.status_code == 200
    assert me_response.json()["data"]["username"] == "alice"


async def test_opencode_login_rejects_wrong_password(client):
    user_id, _ = await _register_user(client)
    await _enable_opencode_with_keys(user_id)

    response = await client.post(
        "/opencode/login",
        json={"username": "alice", "password": "wrong-pass-123"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 40003


async def test_opencode_balance_by_key_returns_balance(client, monkeypatch):
    user_id, _ = await _register_user(client)
    await _enable_opencode_with_keys(user_id)

    def fake_get_user(self, agent_user_id: int):
        assert agent_user_id == 1001
        return type("AgentUserStub", (), {"balance": 12.5})()

    monkeypatch.setattr(AgentOpenAPIClient, "get_user", fake_get_user)

    response = await client.post("/opencode/balance/by-key", json={"api_key": "text-key-123"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == {
        "status": "active",
        "agent_user_id": 1001,
        "agent_balance": 12.5,
        "balance_visible": True,
        "credit_to_agent_rate": 1.0,
    }


async def test_opencode_balance_by_key_rejects_invalid_key(client):
    user_id, _ = await _register_user(client)
    await _enable_opencode_with_keys(user_id)

    response = await client.post("/opencode/balance/by-key", json={"api_key": "bad-key"})

    assert response.status_code == 401
    assert response.json()["code"] == 40003


async def test_opencode_update_feed_returns_latest_mac_yml(client):
    async with AsyncSessionLocal() as session:
        session.add(
            OpenAgentRelease(
                channel="prod",
                version="1.17.14",
                platform="mac",
                arch="arm64",
                file_url="https://magic.shyfai.com/openagent/prod/arm64/openagent-mac-arm64.zip",
                file_sha512="abc123abc123abc123abc123abc123abc123",
                file_size=123456,
                is_active=True,
            )
        )
        await session.commit()

    response = await client.get("/opencode/updates/prod/arm64/latest-mac.yml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/yaml")
    assert 'version: "1.17.14"' in response.text
    assert 'url: "https://magic.shyfai.com/openagent/prod/arm64/openagent-mac-arm64.zip"' in response.text
    assert 'sha512: "abc123abc123abc123abc123abc123abc123"' in response.text
    assert "size: 123456" in response.text


async def test_opencode_update_feed_falls_back_to_universal(client):
    async with AsyncSessionLocal() as session:
        session.add(
            OpenAgentRelease(
                channel="prod",
                version="1.17.15",
                platform="mac",
                arch="universal",
                file_url="https://magic.shyfai.com/openagent/prod/universal/openagent-mac-universal.zip",
                file_sha512="def456def456def456def456def456def456",
                file_size=654321,
                is_active=True,
            )
        )
        await session.commit()

    response = await client.get("/opencode/updates/prod/x64/latest-mac.yml")

    assert response.status_code == 200
    assert 'version: "1.17.15"' in response.text
    assert 'openagent-mac-universal.zip' in response.text


async def test_opencode_update_feed_returns_404_when_empty(client):
    response = await client.get("/opencode/updates/prod/arm64/latest-mac.yml")

    assert response.status_code == 404
    assert response.json()["code"] == 40440


async def test_opencode_usage_returns_only_records_for_current_users_keys(client, monkeypatch):
    user_id, image2_token = await _register_user(client)
    await _enable_opencode_with_keys(user_id)
    captured = {}

    def fake_list_user_usage(
        self,
        *,
        agent_user_id: int,
        page: int,
        page_size: int,
        api_key_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        captured.update({
            "agent_user_id": agent_user_id,
            "api_key_id": api_key_id,
            "page": page,
            "page_size": page_size,
            "start_date": start_date,
            "end_date": end_date,
        })
        return {
            "items": [
                {
                    "id": 11,
                    "api_key": {"name": "文本 Key"},
                    "model": "gpt-test",
                    "reasoning_effort": "medium",
                    "inbound_endpoint": "/v1/chat/completions",
                    "ip_address": "127.0.0.1",
                    "group": {"name": "文本分组"},
                    "request_type": "chat",
                    "billing_mode": "tokens",
                    "input_tokens": 8,
                    "output_tokens": 12,
                    "actual_cost": 0.25,
                    "first_token_ms": 120,
                    "duration_ms": 800,
                    "created_at": "2026-07-04T10:00:00Z",
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
        }

    monkeypatch.setattr(AgentOpenAPIClient, "list_user_usage", fake_list_user_usage)

    response = await client.get(
        "/opencode/usage?page=2&page_size=10",
        headers={"Authorization": f"Bearer {image2_token}"},
    )

    assert response.status_code == 200
    assert captured == {
        "agent_user_id": 1001,
        "api_key_id": 11,
        "page": 2,
        "page_size": 10,
        "start_date": None,
        "end_date": None,
    }
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["page"] == 2
    assert data["page_size"] == 10
    assert data["items"][0] == {
        "id": 11,
        "api_key_name": "文本 Key",
        "model": "gpt-test",
        "ip_address": "127.0.0.1",
        "billing_mode": "tokens",
        "tokens": 20,
        "cost": 0.25,
        "first_token_ms": 120,
        "duration_ms": 800,
        "created_at": "2026-07-04T10:00:00Z",
    }
