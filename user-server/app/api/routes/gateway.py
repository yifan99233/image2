from __future__ import annotations

import logging
import urllib.parse
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Request
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, StreamingResponse

from app.db.session import AsyncSessionLocal
from app.services.gateway_proxy import (
    GatewayRoutingError,
    GatewayTarget,
    build_gateway_upstream_url,
    get_gateway_http_client,
    normalize_gateway_hostname,
    resolve_gateway_target,
)

router = APIRouter(prefix="/v1", tags=["api-gateway"])
logger = logging.getLogger(__name__)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
REQUEST_HEADERS_TO_DROP = HOP_BY_HOP_HEADERS | {
    "content-length",
    "host",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-gateway-site-id",
}
RESPONSE_HEADERS_TO_DROP = HOP_BY_HOP_HEADERS | {"server"}


def gateway_error_response(error: GatewayRoutingError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "type": "gateway_error",
                "code": error.code,
                "message": error.message,
            }
        },
    )


def _forward_request_headers(request: Request, target: GatewayTarget) -> dict[str, str]:
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in REQUEST_HEADERS_TO_DROP
    }
    client_ip = request.client.host if request.client else ""
    if client_ip:
        headers["x-forwarded-for"] = client_ip
    headers["x-forwarded-host"] = normalize_gateway_hostname(request.headers.get("host"))
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-gateway-site-id"] = str(target.site_id)
    return headers


def _forward_response_headers(
    response: httpx.Response,
    *,
    target: GatewayTarget,
) -> list[tuple[str, str]]:
    headers: list[tuple[str, str]] = []
    for name, value in response.headers.multi_items():
        lowered = name.lower()
        if lowered in RESPONSE_HEADERS_TO_DROP:
            continue
        if lowered == "location":
            value = _rewrite_location(value, target)
        headers.append((name, value))
    return headers


def _rewrite_location(value: str, target: GatewayTarget) -> str:
    parsed_upstream = urllib.parse.urlsplit(target.upstream_base_url)
    upstream_origin = f"{parsed_upstream.scheme}://{parsed_upstream.netloc}"
    if value == upstream_origin:
        return target.public_base_url
    if value.startswith(f"{upstream_origin}/"):
        return f"{target.public_base_url}{value[len(upstream_origin):]}"
    return value


async def _request_body(request: Request) -> AsyncIterator[bytes]:
    async for chunk in request.stream():
        if chunk:
            yield chunk


async def _close_upstream_response(response: httpx.Response) -> None:
    await response.aclose()


async def _resolve_request_target(request: Request) -> GatewayTarget:
    async with AsyncSessionLocal() as db:
        return await resolve_gateway_target(db, request)


@router.api_route(
    "/",
    methods=["GET", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def gateway_status(request: Request):
    try:
        target = await _resolve_request_target(request)
    except GatewayRoutingError as error:
        return gateway_error_response(error)
    return JSONResponse(
        content={
            "object": "api_gateway",
            "status": "ok",
            "site_id": target.site_id,
        }
    )


@router.api_route(
    "/{gateway_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def forward_v1_request(request: Request, gateway_path: str):
    try:
        target = await _resolve_request_target(request)
    except GatewayRoutingError as error:
        return gateway_error_response(error)

    upstream_url = build_gateway_upstream_url(
        target.upstream_base_url,
        f"/v1/{gateway_path}",
        request.url.query,
    )
    client = get_gateway_http_client()
    upstream_request = client.build_request(
        request.method,
        upstream_url,
        headers=_forward_request_headers(request, target),
        content=None if request.method in {"GET", "HEAD", "OPTIONS"} else _request_body(request),
    )
    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException:
        logger.warning(
            "gateway upstream timeout site_id=%s method=%s path=%s",
            target.site_id,
            request.method,
            request.url.path,
        )
        return gateway_error_response(
            GatewayRoutingError(
                "上游请求超时",
                status_code=504,
                code="gateway_upstream_timeout",
            )
        )
    except httpx.RequestError as error:
        logger.warning(
            "gateway upstream unavailable site_id=%s method=%s path=%s error=%s",
            target.site_id,
            request.method,
            request.url.path,
            type(error).__name__,
        )
        return gateway_error_response(
            GatewayRoutingError(
                "上游服务暂时不可用",
                status_code=502,
                code="gateway_upstream_unavailable",
            )
        )

    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=dict(_forward_response_headers(upstream_response, target=target)),
        background=BackgroundTask(_close_upstream_response, upstream_response),
    )
