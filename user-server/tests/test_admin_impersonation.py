from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request

from app.api.routes import auth
from app.core.exceptions import BusinessError
from app.schemas.auth import ImpersonationExchangeRequest
from app.services.security import verify_access_token


def request_for(host: str = "magic-demo.shyfai.com") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/admin-impersonation/exchange",
            "headers": [(b"host", host.encode("ascii"))],
            "client": ("127.0.0.1", 1234),
            "scheme": "https",
            "server": (host, 443),
        }
    )


@pytest.mark.asyncio
async def test_exchange_admin_impersonation_returns_marked_short_lived_token(monkeypatch) -> None:
    grant = SimpleNamespace(user_id=42, site_id=3, admin_id=7, admin_username="yifan")
    claim_result = SimpleNamespace(one_or_none=lambda: grant)
    user = SimpleNamespace(
        id=42,
        username="target",
        email="target@example.com",
        nickname=None,
        avatar_url=None,
        is_active=True,
        invited_by_user_id=None,
        created_at=None,
        last_login_at=None,
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=claim_result),
        scalar=AsyncMock(return_value=user),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(auth, "current_site_id", AsyncMock(return_value=3))

    response = await auth.exchange_admin_impersonation(
        ImpersonationExchangeRequest(code="x" * 32),
        request_for(),
        db,
    )

    payload = verify_access_token(response.data.access_token)
    assert payload["sub"] == "42"
    assert payload["impersonation"] is True
    assert payload["impersonated_by_admin_username"] == "yifan"
    assert payload["exp"] - payload["iat"] == 3600
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_exchange_admin_impersonation_rejects_used_or_expired_code(monkeypatch) -> None:
    claim_result = SimpleNamespace(one_or_none=lambda: None)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=claim_result),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(auth, "current_site_id", AsyncMock(return_value=3))

    with pytest.raises(BusinessError) as exc_info:
        await auth.exchange_admin_impersonation(
            ImpersonationExchangeRequest(code="x" * 32),
            request_for(),
            db,
        )

    assert exc_info.value.code == 40020
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_exchange_admin_impersonation_consumes_code_on_wrong_site(monkeypatch) -> None:
    grant = SimpleNamespace(user_id=42, site_id=3, admin_id=7, admin_username="yifan")
    claim_result = SimpleNamespace(one_or_none=lambda: grant)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=claim_result),
        scalar=AsyncMock(),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(auth, "current_site_id", AsyncMock(return_value=4))

    with pytest.raises(BusinessError) as exc_info:
        await auth.exchange_admin_impersonation(
            ImpersonationExchangeRequest(code="x" * 32),
            request_for(),
            db,
        )

    assert exc_info.value.code == 40320
    db.commit.assert_awaited_once()
    db.scalar.assert_not_awaited()
