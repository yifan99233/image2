from __future__ import annotations

import httpx
import pytest

from app.api.routes import gateway
from app.services.gateway_proxy import (
    GatewayRoutingError,
    GatewayTarget,
    build_gateway_upstream_url,
    gateway_candidate_origins,
    gateway_public_base_url,
    normalize_gateway_hostname,
    normalize_public_base_url,
    normalize_upstream_base_url,
)
from app.services.site_scope import normalized_host, site_host_aliases


class AsyncBytes(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self):
        yield self.content


def test_normalize_gateway_hostname_removes_port_and_trailing_dot():
    assert normalize_gateway_hostname("Magic.Example.Test.:443") == "magic.example.test"


def test_site_host_aliases_keep_cn_and_com_tenant_hosts_equivalent():
    assert site_host_aliases("magic-lqcm.shyfai.cn") == (
        "magic-lqcm.shyfai.com",
        "magic-lqcm.shyfai.cn",
    )
    assert site_host_aliases("magic-lqcm.shyfai.com") == (
        "magic-lqcm.shyfai.com",
        "magic-lqcm.shyfai.cn",
    )
    assert site_host_aliases("unrelated.example.test") == ("unrelated.example.test",)
    assert normalized_host("https://MAGIC-LQCM.shyfai.cn:443/path") == "magic-lqcm.shyfai.cn"


def test_gateway_cn_alias_matches_com_config_without_changing_public_host():
    assert gateway_candidate_origins("magic-lqcm.shyfai.cn") == (
        "https://magic-lqcm.shyfai.com",
        "http://magic-lqcm.shyfai.com",
        "https://magic-lqcm.shyfai.cn",
        "http://magic-lqcm.shyfai.cn",
    )
    assert (
        gateway_public_base_url(
            "https://magic-lqcm.shyfai.com",
            "magic-lqcm.shyfai.cn",
        )
        == "https://magic-lqcm.shyfai.cn"
    )


def test_build_gateway_upstream_url_does_not_duplicate_v1():
    assert (
        build_gateway_upstream_url(
            "https://sub2.internal.example/v1/",
            "/v1/responses",
            "stream=true",
        )
        == "https://sub2.internal.example/v1/responses?stream=true"
    )


@pytest.mark.parametrize(
    ("normalizer", "value"),
    [
        (normalize_public_base_url, "https://user:pass@magic.example.test"),
        (normalize_public_base_url, "https://magic.example.test?internal=true"),
        (normalize_upstream_base_url, "ftp://sub2.internal.example"),
        (normalize_upstream_base_url, "https://sub2.internal.example/v1#fragment"),
    ],
)
def test_gateway_base_url_normalizers_reject_unsafe_values(normalizer, value):
    with pytest.raises(GatewayRoutingError):
        normalizer(value)


async def test_gateway_forwards_existing_key_and_rewrites_upstream_location(client, monkeypatch):
    target = GatewayTarget(
        site_id=8,
        public_base_url="https://magic.example.test",
        upstream_base_url="https://sub2.internal.example/v1",
    )
    captured: dict[str, object] = {}

    async def fake_resolve_gateway_target(_db, _request):
        return target

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["forwarded_host"] = request.headers.get("x-forwarded-host")
        captured["site_id"] = request.headers.get("x-gateway-site-id")
        return httpx.Response(
            307,
            headers={
                "location": "https://sub2.internal.example/v1/models/next",
                "server": "must-not-leak",
            },
            stream=AsyncBytes(b""),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as upstream_client:
        monkeypatch.setattr(gateway, "resolve_gateway_target", fake_resolve_gateway_target)
        monkeypatch.setattr(gateway, "get_gateway_http_client", lambda: upstream_client)

        response = await client.get(
            "/v1/models?capability=text",
            headers={
                "Host": "magic.example.test",
                "Authorization": "Bearer existing-sub2-key",
            },
            follow_redirects=False,
        )

    assert response.status_code == 307
    assert response.headers["location"] == "https://magic.example.test/v1/models/next"
    assert "server" not in response.headers
    assert captured == {
        "method": "GET",
        "url": "https://sub2.internal.example/v1/models?capability=text",
        "authorization": "Bearer existing-sub2-key",
        "forwarded_host": "magic.example.test",
        "site_id": "8",
    }


async def test_gateway_streams_request_and_response_without_changing_api_key(client, monkeypatch):
    target = GatewayTarget(
        site_id=9,
        public_base_url="https://tenant.example.test",
        upstream_base_url="https://sub2.internal.example",
    )
    captured: dict[str, object] = {}

    async def fake_resolve_gateway_target(_db, _request):
        return target

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        captured["body"] = await request.aread()
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=AsyncBytes(b'data: {"type":"response.completed"}\n\n'),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler)) as upstream_client:
        monkeypatch.setattr(gateway, "resolve_gateway_target", fake_resolve_gateway_target)
        monkeypatch.setattr(gateway, "get_gateway_http_client", lambda: upstream_client)

        response = await client.post(
            "/v1/responses?stream=true",
            headers={
                "Host": "tenant.example.test",
                "X-API-Key": "existing-sub2-key",
            },
            content=b'{"model":"gpt-5.6-sol","stream":true}',
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == b'data: {"type":"response.completed"}\n\n'
    assert captured == {
        "url": "https://sub2.internal.example/v1/responses?stream=true",
        "api_key": "existing-sub2-key",
        "body": b'{"model":"gpt-5.6-sol","stream":true}',
    }


async def test_gateway_unknown_host_fails_closed_without_contacting_upstream(client, monkeypatch):
    async def fake_resolve_gateway_target(_db, _request):
        raise GatewayRoutingError(
            "该域名未绑定可用子站",
            status_code=404,
            code="gateway_site_not_found",
        )

    def fail_if_client_requested():
        raise AssertionError("unknown tenant must not contact an upstream")

    monkeypatch.setattr(gateway, "resolve_gateway_target", fake_resolve_gateway_target)
    monkeypatch.setattr(gateway, "get_gateway_http_client", fail_if_client_requested)

    response = await client.get("/v1/models", headers={"Host": "unknown.example.test"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "type": "gateway_error",
            "code": "gateway_site_not_found",
            "message": "该域名未绑定可用子站",
        }
    }


async def test_gateway_base_endpoint_reports_ready_without_contacting_upstream(client, monkeypatch):
    target = GatewayTarget(
        site_id=10,
        public_base_url="https://tenant.example.test",
        upstream_base_url="https://sub2.internal.example",
    )

    async def fake_resolve_gateway_target(_db, _request):
        return target

    def fail_if_client_requested():
        raise AssertionError("gateway base status must not contact an upstream")

    monkeypatch.setattr(gateway, "resolve_gateway_target", fake_resolve_gateway_target)
    monkeypatch.setattr(gateway, "get_gateway_http_client", fail_if_client_requested)

    response = await client.get("/v1/", headers={"Host": "tenant.example.test"})

    assert response.status_code == 200
    assert response.json() == {
        "object": "api_gateway",
        "status": "ok",
        "site_id": 10,
    }
