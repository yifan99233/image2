from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

import httpx
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import AgentConfig
from app.services.site_scope import site_configs_table, site_host_aliases


class GatewayRoutingError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class GatewayTarget:
    site_id: int
    public_base_url: str
    upstream_base_url: str


_gateway_http_client: httpx.AsyncClient | None = None


def normalize_gateway_hostname(value: str | None) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value if "://" in value else f"//{value}")
    hostname = (parsed.hostname or "").strip().rstrip(".").lower()
    if not hostname:
        return ""
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def normalize_public_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    hostname = normalize_gateway_hostname(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise GatewayRoutingError(
            "子站公开地址配置无效",
            status_code=503,
            code="gateway_public_url_invalid",
        )
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{hostname}{port}"


def normalize_upstream_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise GatewayRoutingError(
            "网关上游地址配置无效",
            status_code=503,
            code="gateway_upstream_invalid",
        )
    return value.strip().rstrip("/")


def build_gateway_upstream_url(upstream_base_url: str, request_path: str, query: str = "") -> str:
    normalized_base = normalize_upstream_base_url(upstream_base_url)
    normalized_path = request_path if request_path.startswith("/") else f"/{request_path}"
    if normalized_base.lower().endswith("/v1") and normalized_path.lower().startswith("/v1/"):
        normalized_path = normalized_path[3:]
    target = f"{normalized_base}{normalized_path}"
    return f"{target}?{query}" if query else target


def gateway_candidate_origins(hostname: str) -> tuple[str, ...]:
    return tuple(
        f"{scheme}://{alias_host}"
        for alias_host in site_host_aliases(hostname)
        for scheme in ("https", "http")
    )


def gateway_public_base_url(configured_public_base_url: str, request_hostname: str) -> str:
    configured_url = normalize_public_base_url(configured_public_base_url)
    configured_scheme = urllib.parse.urlsplit(configured_url).scheme
    return f"{configured_scheme}://{request_hostname}"


async def public_gateway_base_url_for_site(db: AsyncSession, site_id: int) -> str:
    frontend_url = await db.scalar(
        select(site_configs_table.c.frontend_url).where(
            site_configs_table.c.id == site_id,
            site_configs_table.c.is_enabled.is_(True),
        )
    )
    if not frontend_url:
        raise GatewayRoutingError(
            "子站公开地址尚未配置",
            status_code=503,
            code="gateway_public_url_missing",
        )
    return normalize_public_base_url(str(frontend_url))


async def resolve_gateway_target(db: AsyncSession, request: Request) -> GatewayTarget:
    hostname = normalize_gateway_hostname(request.headers.get("host"))
    if not hostname:
        raise GatewayRoutingError("请求域名无效", status_code=400, code="gateway_host_invalid")

    candidate_origins = gateway_candidate_origins(hostname)
    site_row = (
        await db.execute(
            select(
                site_configs_table.c.id,
                site_configs_table.c.frontend_url,
            )
            .where(
                site_configs_table.c.is_enabled.is_(True),
                func.lower(func.rtrim(site_configs_table.c.frontend_url, "/")).in_(candidate_origins),
            )
            .limit(1)
        )
    ).first()
    if site_row is None:
        raise GatewayRoutingError(
            "该域名未绑定可用子站",
            status_code=404,
            code="gateway_site_not_found",
        )

    config = await db.scalar(
        select(AgentConfig).where(
            AgentConfig.site_id == int(site_row.id),
            AgentConfig.is_enabled.is_(True),
        )
    )
    if config is None or not str(config.base_url or "").strip():
        raise GatewayRoutingError(
            "该子站的 API 上游尚未配置",
            status_code=503,
            code="gateway_upstream_missing",
        )

    public_base_url = gateway_public_base_url(str(site_row.frontend_url), hostname)
    upstream_base_url = normalize_upstream_base_url(str(config.base_url))
    if normalize_gateway_hostname(public_base_url) == normalize_gateway_hostname(upstream_base_url):
        raise GatewayRoutingError(
            "网关上游不能指向当前子站域名",
            status_code=503,
            code="gateway_upstream_loop",
        )
    return GatewayTarget(
        site_id=int(site_row.id),
        public_base_url=public_base_url,
        upstream_base_url=upstream_base_url,
    )


def get_gateway_http_client() -> httpx.AsyncClient:
    global _gateway_http_client
    if _gateway_http_client is None or _gateway_http_client.is_closed:
        _gateway_http_client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=settings.gateway_connect_timeout_seconds,
                read=settings.gateway_read_timeout_seconds,
                write=settings.gateway_write_timeout_seconds,
                pool=settings.gateway_connect_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=settings.gateway_max_connections,
                max_keepalive_connections=settings.gateway_max_keepalive_connections,
            ),
        )
    return _gateway_http_client


async def close_gateway_http_client() -> None:
    global _gateway_http_client
    if _gateway_http_client is not None and not _gateway_http_client.is_closed:
        await _gateway_http_client.aclose()
    _gateway_http_client = None
