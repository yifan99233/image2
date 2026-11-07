import asyncio

import pytest
from starlette.requests import Request

import app.api.routes.site as site_routes
from app.api.routes.site import default_site_config, site_config_out


def test_public_site_config_exposes_configured_icon():
    icon_url = "https://cdn.example.com/brand/icon.png"

    assert site_config_out({"site_icon_url": icon_url})["site_icon_url"] == icon_url


def test_public_site_config_falls_back_to_default_icon():
    assert site_config_out({})["site_icon_url"] == default_site_config()["site_icon_url"]


def _request_for_host(host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/site/config",
            "headers": [(b"host", host.encode())],
        }
    )


@pytest.mark.asyncio
async def test_public_site_config_cache_collapses_misses_and_expires(monkeypatch):
    site_routes._site_config_cache.clear()
    monkeypatch.setattr(site_routes, "_site_config_cache_lock", asyncio.Lock())
    monkeypatch.setattr(site_routes, "SITE_CONFIG_CACHE_TTL_SECONDS", 0.01)
    calls = 0

    async def fake_load(_request, _db):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"site_name": f"version-{calls}"}

    monkeypatch.setattr(site_routes, "_load_site_config", fake_load)
    request = _request_for_host("tenant.example.com")

    responses = await asyncio.gather(
        *(site_routes.site_config(request, object()) for _ in range(8))
    )
    assert calls == 1
    assert {response.data["site_name"] for response in responses} == {"version-1"}

    await asyncio.sleep(0.02)
    refreshed = await site_routes.site_config(request, object())
    assert calls == 2
    assert refreshed.data["site_name"] == "version-2"
