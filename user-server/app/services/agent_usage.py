from __future__ import annotations

import asyncio
from datetime import datetime

from app.services.agent_openapi import AgentOpenAPIClient

EXTERNAL_USAGE_PAGE_SIZE_MAX = 100
USAGE_FETCH_CONCURRENCY = 8


def nested_value(row: dict, key: str, nested_key: str = "name") -> str:
    value = row.get(key)
    if isinstance(value, dict):
        nested = value.get(nested_key)
        return str(nested) if nested is not None else ""
    return ""


def usage_record_api_key_id(row: object) -> int | None:
    data = row if isinstance(row, dict) else {}
    value = data.get("api_key_id")
    if value is None and isinstance(data.get("api_key"), dict):
        value = data["api_key"].get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def usage_record_out(row: object, *, member: dict | None = None) -> dict:
    data = row if isinstance(row, dict) else {}
    input_tokens = int(data.get("input_tokens") or 0)
    output_tokens = int(data.get("output_tokens") or 0)
    cache_creation_tokens = int(data.get("cache_creation_tokens") or 0)
    cache_read_tokens = int(data.get("cache_read_tokens") or 0)
    image_output_tokens = int(data.get("image_output_tokens") or 0)
    payload = {
        "id": data.get("id") or data.get("request_id") or data.get("created_at") or "",
        "api_key_name": nested_value(data, "api_key"),
        "model": data.get("model") or "",
        "ip_address": data.get("ip_address") or "",
        "billing_mode": data.get("billing_mode") or "",
        "tokens": input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens + image_output_tokens,
        "cost": float(data.get("actual_cost") if data.get("actual_cost") is not None else data.get("total_cost") or 0),
        "first_token_ms": data.get("first_token_ms"),
        "duration_ms": data.get("duration_ms"),
        "created_at": data.get("created_at") or "",
    }
    if member is not None:
        payload["member"] = member
    return payload


def _record_sort_key(row: object) -> tuple[float, str]:
    data = row if isinstance(row, dict) else {}
    raw_created_at = str(data.get("created_at") or "")
    try:
        timestamp = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        timestamp = 0
    return timestamp, str(data.get("id") or data.get("request_id") or "")


async def list_usage_for_api_keys(
    client: AgentOpenAPIClient,
    *,
    agent_user_id: int,
    api_key_ids: list[int],
    page: int,
    page_size: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    normalized_key_ids = sorted({int(key_id) for key_id in api_key_ids if int(key_id) > 0})
    if not normalized_key_ids:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    if len(normalized_key_ids) == 1:
        return await asyncio.to_thread(
            client.list_user_usage,
            agent_user_id=agent_user_id,
            api_key_id=normalized_key_ids[0],
            page=page,
            page_size=page_size,
            start_date=start_date,
            end_date=end_date,
        )

    target_count = page * page_size
    semaphore = asyncio.Semaphore(USAGE_FETCH_CONCURRENCY)

    async def fetch_page(key_id: int, external_page: int, external_page_size: int) -> dict:
        async with semaphore:
            return await asyncio.to_thread(
                client.list_user_usage,
                agent_user_id=agent_user_id,
                api_key_id=key_id,
                page=external_page,
                page_size=external_page_size,
                start_date=start_date,
                end_date=end_date,
            )

    first_page_size = min(EXTERNAL_USAGE_PAGE_SIZE_MAX, target_count)
    first_pages = await asyncio.gather(
        *(fetch_page(key_id, 1, first_page_size) for key_id in normalized_key_ids)
    )
    streams: dict[int, list[object]] = {
        key_id: list(result["items"])
        for key_id, result in zip(normalized_key_ids, first_pages)
    }
    totals = {
        key_id: int(result["total"])
        for key_id, result in zip(normalized_key_ids, first_pages)
    }

    if target_count > first_page_size:
        requests: list[tuple[int, int]] = []
        for key_id in normalized_key_ids:
            required = min(target_count, totals[key_id])
            external_page = 2
            while (external_page - 1) * EXTERNAL_USAGE_PAGE_SIZE_MAX < required:
                requests.append((key_id, external_page))
                external_page += 1
        additional = await asyncio.gather(
            *(fetch_page(key_id, external_page, EXTERNAL_USAGE_PAGE_SIZE_MAX) for key_id, external_page in requests)
        )
        for (key_id, _external_page), result in zip(requests, additional):
            streams[key_id].extend(result["items"])

    merged = [row for rows in streams.values() for row in rows]
    merged.sort(key=_record_sort_key, reverse=True)
    offset = (page - 1) * page_size
    return {
        "items": merged[offset : offset + page_size],
        "total": sum(totals.values()),
        "page": page,
        "page_size": page_size,
    }
