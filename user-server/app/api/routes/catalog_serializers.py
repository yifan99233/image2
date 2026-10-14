import json
from datetime import datetime
from urllib.parse import urlparse

from app.services.image_uploads import is_r2_hot_url_valid
from app.services.image_thumbnails import thumbnail_path
from app.services.asset_urls import canonicalize_asset_url

USER_IMAGE_TASK_FAILURE_MESSAGE = "生成失败 积分已退还 请重新生成"


def guess_asset_mime_type(url: str | None) -> str:
    path = urlparse((url or "").strip()).path.lower()
    if path.endswith(".webm"):
        return "video/webm"
    if path.endswith(".mov"):
        return "video/quicktime"
    if path.endswith(".m4v"):
        return "video/x-m4v"
    if path.endswith((".mp4", ".mpeg4")):
        return "video/mp4"
    if path.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if path.endswith(".webp"):
        return "image/webp"
    if path.endswith(".gif"):
        return "image/gif"
    if path.endswith(".png"):
        return "image/png"
    # Provider native video links often omit extensions; keep a video-friendly default only
    # when path clearly mentions video, otherwise default to png for legacy image assets.
    lowered = (url or "").lower()
    if any(token in lowered for token in ("/video", "video/", "videos/", "text_to_video", "image_to_video", ".mp4")):
        return "video/mp4"
    return "image/png"


def serialize_asset(
    url: str | None,
    source: str = "model_output",
    *,
    local_url: str | None = None,
    r2_url: str | None = None,
    r2_expires_at=None,
) -> dict | None:
    if not url:
        return None
    durable_url = canonicalize_asset_url(local_url or url)
    hot_url = canonicalize_asset_url(r2_url) or None
    display_url = hot_url if is_r2_hot_url_valid(hot_url, r2_expires_at) else durable_url
    return {
        "id": 0,
        "url": display_url,
        "local_url": durable_url,
        "r2_url": hot_url,
        "r2_expires_at": r2_expires_at.isoformat() if r2_expires_at else None,
        "mime_type": guess_asset_mime_type(display_url),
        "width": None,
        "height": None,
        "size_bytes": 0,
        "sha256": "",
        "source": source,
    }


def input_urls_from_row(row) -> list[str]:
    urls: list[str] = []
    raw_urls = row.get("input_image_urls")
    if isinstance(raw_urls, str) and raw_urls.strip():
        try:
            parsed = json.loads(raw_urls)
            if isinstance(parsed, list):
                urls = [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            urls = []
    if not urls and row.get("input_image_url"):
        urls = [row.get("input_image_url")]
    return urls


def input_assets_from_row(row, source: str = "upload") -> list[dict]:
    return [asset for asset in (serialize_asset(url, source) for url in input_urls_from_row(row)) if asset]


def iso_datetime(value) -> str | None:
    return value.isoformat() if value else None


def duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end or end < start:
        return None
    return max(0, int(round((end - start).total_seconds())))


def _display_task_aspect(work_type: str | None, raw: str | None) -> tuple[str, str]:
    """Return (aspect_ratio, duration) for API clients."""
    value = (raw or "").strip()
    wt = (work_type or "").strip()
    is_video = wt in {"text_to_video", "image_to_video"} or "|" in value
    if not is_video:
        return value, ""
    if "|" in value:
        left, right = value.split("|", 1)
        ratio = left.strip() or "16:9"
        duration = right.strip()
        return ratio, duration
    # Legacy video tasks stored duration code only in aspect_ratio.
    if value and ":" not in value:
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return "16:9", value
    return value, ""


def serialize_task(row) -> dict:
    input_assets = input_assets_from_row(row, "upload")
    for index, asset in enumerate(input_assets):
        if asset["mime_type"].startswith("image/"):
            asset["thumbnail_url"] = thumbnail_path(int(row.get("id")), asset["local_url"], input_index=index)
    output_asset = serialize_asset(
        row.get("output_image_url"),
        local_url=row.get("output_image_url"),
        r2_url=row.get("output_image_r2_url"),
        r2_expires_at=row.get("output_image_r2_expires_at"),
    )
    if output_asset and output_asset["mime_type"].startswith("image/"):
        output_asset["thumbnail_url"] = thumbnail_path(int(row.get("id")), output_asset["local_url"])
    status = row.get("status")
    progress_stage = status
    if status == "running":
        # The provider completion callback persists provider_http_status before the
        # returned image is downloaded and stored. Keep the operational status as
        # running so polling/concurrency semantics do not change, while exposing
        # the user-visible transfer stage separately.
        progress_stage = "downloading" if row.get("provider_http_status") is not None else "generating"
    created_at = row.get("created_at")
    worker_started_at = row.get("worker_started_at")
    finished_at = row.get("finished_at")
    aspect_ratio, duration = _display_task_aspect(row.get("work_type"), row.get("aspect_ratio"))
    return {
        "id": row.get("id"),
        "task_no": row.get("task_no"),
        "batch_id": row.get("batch_id") or "",
        "retry_of_task_id": row.get("retry_of_task_id"),
        "retry_of_batch_id": row.get("retry_of_batch_id") or "",
        "input_group_id": row.get("input_group_id") or "",
        "input_group_name": row.get("input_group_name") or "",
        "input_group_path": row.get("input_group_path") or "",
        "work_type": row.get("work_type"),
        "model_id": row.get("model_id"),
        "model_name": row.get("model_name") or "",
        "prompt": row.get("prompt") or "",
        "resolution": row.get("resolution") or "",
        "aspect_ratio": aspect_ratio,
        "quality": row.get("quality") or "auto",
        "duration": duration,
        "credit_cost": row.get("credit_cost") or 0,
        "status": status,
        "progress_stage": progress_stage,
        # 失败时把真实错误 message 给用户（超时/内容策略等）；没有落库文案时再兜底
        "failure_message": (
            (row.get("failure_message") or USER_IMAGE_TASK_FAILURE_MESSAGE)
            if status in {"failed", "refunded"}
            else row.get("failure_message")
        ),
        "input_images": input_assets,
        "output_images": [output_asset] if output_asset else [],
        "is_collected": bool(row.get("is_collected")),
        "owner_user_id": row.get("user_id"),
        "owner_name": row.get("owner_name") or "",
        "created_at": iso_datetime(created_at) or "",
        "worker_started_at": iso_datetime(worker_started_at),
        "finished_at": iso_datetime(finished_at),
        "queue_duration_seconds": duration_seconds(created_at, worker_started_at),
        "generation_duration_seconds": duration_seconds(worker_started_at, finished_at),
        "total_duration_seconds": duration_seconds(created_at, finished_at),
    }


def serialize_task_status(row) -> dict:
    """Small polling DTO; immutable task metadata stays in the client cache."""
    status = row.get("status")
    progress_stage = status
    if status == "running":
        progress_stage = "downloading" if row.get("provider_http_status") is not None else "generating"
    output_asset = serialize_asset(
        row.get("output_image_url"),
        local_url=row.get("output_image_url"),
        r2_url=row.get("output_image_r2_url"),
        r2_expires_at=row.get("output_image_r2_expires_at"),
    )
    if output_asset and output_asset["mime_type"].startswith("image/"):
        output_asset["thumbnail_url"] = thumbnail_path(int(row.get("id")), output_asset["local_url"])
    return {
        "id": row.get("id"),
        "status": status,
        "progress_stage": progress_stage,
        "failure_message": (
            (row.get("failure_message") or USER_IMAGE_TASK_FAILURE_MESSAGE)
            if status in {"failed", "refunded"}
            else row.get("failure_message")
        ),
        "output_images": [output_asset] if output_asset else [],
        "worker_started_at": iso_datetime(row.get("worker_started_at")),
        "finished_at": iso_datetime(row.get("finished_at")),
    }


def serialize_gallery_work(row) -> dict:
    output_asset = serialize_asset(
        row.get("output_image_url"),
        local_url=row.get("output_image_url"),
        r2_url=row.get("output_image_r2_url"),
        r2_expires_at=row.get("output_image_r2_expires_at"),
    ) or serialize_asset("")
    input_assets = input_assets_from_row(row, "upload")
    work_type = row.get("work_type")
    aspect_ratio, _ = _display_task_aspect(work_type, row.get("aspect_ratio"))
    is_edit_work = work_type in {"image_edit", "image_to_image", "batch_edit"}
    return {
        "id": row.get("id"),
        "task_id": row.get("id"),
        "work_type": work_type or "",
        "aspect_ratio": aspect_ratio,
        "category": row.get("model_name") or row.get("work_type") or "AI 创作",
        "title": row.get("gallery_title") or row.get("model_name") or "精选示范",
        "prompt_snapshot": row.get("prompt") or "",
        "cover_asset": output_asset,
        "input_assets": input_assets if is_edit_work else [],
        "output_assets": [output_asset] if output_asset else [],
        "is_collected": False,
        "is_recommended": True,
        "owner_user_id": row.get("user_id"),
        "owner_name": row.get("owner_name") or "",
        "created_at": row.get("gallery_featured_at").isoformat() if row.get("gallery_featured_at") else row.get("created_at").isoformat(),
    }


def work_category(work_type: str | None) -> str:
    if work_type in {"image_edit", "image_to_image", "batch_edit"}:
        return "图片处理"
    if work_type in {"text_to_image", "batch_generate"}:
        return "文生图"
    if work_type in {"text_to_video", "image_to_video"}:
        return "视频创作"
    return "AI 创作"


def serialize_user_work(row) -> dict:
    requested = bool(row.get("is_gallery_featured"))
    reviewed = row.get("gallery_featured_by") is not None
    output_asset = serialize_asset(
        row.get("output_image_url"),
        local_url=row.get("output_image_url"),
        r2_url=row.get("output_image_r2_url"),
        r2_expires_at=row.get("output_image_r2_expires_at"),
    ) or serialize_asset("")
    input_assets = input_assets_from_row(row, "upload")
    aspect_ratio, _ = _display_task_aspect(row.get("work_type"), row.get("aspect_ratio"))
    return {
        "id": row.get("id"),
        "task_id": row.get("id"),
        "aspect_ratio": aspect_ratio,
        "category": work_category(row.get("work_type")),
        "title": row.get("gallery_title") or row.get("input_group_name") or row.get("model_name") or "AI 作品",
        "prompt_snapshot": row.get("prompt") or "",
        "cover_asset": output_asset,
        "input_assets": input_assets,
        "output_assets": [output_asset],
        "is_collected": bool(row.get("is_collected")),
        "is_recommended": requested and reviewed,
        "gallery_review_status": ("approved" if reviewed else "pending") if requested else ("rejected" if reviewed else "none"),
        "owner_user_id": row.get("user_id"),
        "owner_name": row.get("owner_name") or "",
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else "",
    }
