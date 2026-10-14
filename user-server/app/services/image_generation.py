import base64
import errno
import http.client
import json
import logging
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import perf_counter, sleep
from typing import Literal
from uuid import uuid4

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.services.image_parameters import normalize_image_quality

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationModelConfig:
    provider_code: str
    provider_name: str
    base_url: str
    access_mode: str
    api_key: str
    auth_type: str
    timeout_seconds: int
    vendor_model: str
    disable_retry: bool = False


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    mime_type: str
    provider_request_id: str = ""
    provider_request_snapshot: dict | None = None
    provider_response_summary: dict | None = None
    provider_http_status: int | None = None
    source_url: str | None = None
    # The upstream may already have a short-lived R2 object. Keep that URL
    # separate from source_url (which is used by native video storage).
    hot_url: str | None = None


IMAGE_EDIT_INSTRUCTION = (
    "你正在执行图像编辑任务。必须以随附输入图片作为主要视觉参考，"
    "保留用户未要求改变的主体、构图、轮廓、图标/文字/产品/人物身份和整体空间关系；"
    "只按用户的修改要求调整画面。不要脱离原图重新创作，不要生成无关场景。"
)

MODEL_RATE_LIMIT_MESSAGE = "上游模型服务请求过于频繁，请稍后再试。"
MODEL_IMAGE_CAPACITY_MESSAGE = "图片生成服务当前无可用容量，请稍后再试或切换模型。"
MODEL_SAFETY_REJECTED_MESSAGE = "内容策略拦截，请修改提示词后重试"
MODEL_TIMEOUT_MESSAGE = "模型超时，请重试"
# 超分网关超时：HTTP 400 + message/code 超时；业务码专用于「仅超时可重试」。
MODEL_TIMEOUT_CODE = 50231
MODEL_SAFETY_CODE = 50232
RESULT_DOWNLOAD_TIMEOUT_CODE = 50233
RESULT_DOWNLOAD_TIMEOUT_MESSAGE = "模型结果下载超时，请重试"
INPUT_DOWNLOAD_TIMEOUT_CODE = 50235
INPUT_DOWNLOAD_TIMEOUT_MESSAGE = "输入原图下载超时，请重试"
INPUT_DOWNLOAD_FAILED_CODE = 50236
INPUT_DOWNLOAD_FAILED_MESSAGE = "输入原图下载失败，请重试"
RESULT_DOWNLOAD_FAILED_CODE = 50212
RESULT_DOWNLOAD_FAILED_MESSAGE = "模型结果下载失败，请重试"
DEFAULT_MODEL_TASK_TIMEOUT_SECONDS = 120
MIN_MODEL_TASK_TIMEOUT_SECONDS = 10
MAX_MODEL_TASK_TIMEOUT_SECONDS = 3600
ADOBE_VIDEO_MODEL_PREFIXES = (
    "agent5-veo31",
    "agent5-kling-o3",
    "agent5-kling3",
    "agent5-seedance",
    "firefly-veo31",
    "firefly-kling-o3",
    "firefly-kling3",
    "firefly-seedance",
)
DOWNLOAD_CHUNK_BYTES = 256 * 1024
PROVIDER_RESPONSE_CHUNK_BYTES = 64 * 1024
VIDEO_POLL_RESPONSE_MAX_BYTES = 4 * 1024 * 1024
TRANSIENT_DOWNLOAD_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
TRANSIENT_DOWNLOAD_ERRNOS = frozenset(
    {
        errno.EPIPE,
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.ENETRESET,
        errno.ENETUNREACH,
        errno.ETIMEDOUT,
    }
)
DownloadKind = Literal["input", "result"]


def _read_response_bytes(response, max_bytes: int, *, label: str) -> bytes:
    """Read an upstream response with a hard memory bound."""
    limit = max(1, int(max_bytes))
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise BusinessError(
                    f"{label}响应过大，最大允许 {limit // (1024 * 1024)}MB",
                    code=50234,
                    status_code=502,
                )
        except ValueError:
            pass
    content_buffer = bytearray()
    while True:
        chunk = response.read(PROVIDER_RESPONSE_CHUNK_BYTES)
        if not chunk:
            break
        content_buffer.extend(chunk)
        if len(content_buffer) > limit:
            raise BusinessError(
                f"{label}响应过大，最大允许 {limit // (1024 * 1024)}MB",
                code=50234,
                status_code=502,
            )
    return bytes(content_buffer)


def effective_model_timeout_seconds(value: int | None) -> int:
    """Resolve a model's configured task budget within the platform safety cap."""
    try:
        timeout_seconds = int(value or DEFAULT_MODEL_TASK_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return DEFAULT_MODEL_TASK_TIMEOUT_SECONDS
    return max(MIN_MODEL_TASK_TIMEOUT_SECONDS, min(timeout_seconds, MAX_MODEL_TASK_TIMEOUT_SECONDS))


def _request_deadline_monotonic(timeout_seconds: int | None) -> float:
    return perf_counter() + effective_model_timeout_seconds(timeout_seconds)


def _remaining_request_timeout(deadline_monotonic: float) -> float:
    remaining = deadline_monotonic - perf_counter()
    if remaining <= 0:
        raise BusinessError(MODEL_TIMEOUT_MESSAGE, code=MODEL_TIMEOUT_CODE, status_code=400)
    # urllib accepts floats. Keeping the real remainder prevents an endpoint
    # fallback, download, or retry from silently receiving a fresh full budget.
    return max(0.05, remaining)


def _provider_kind(config: GenerationModelConfig) -> str:
    if config.access_mode == "sdk":
        return "openai_chat_completions"
    provider_code = config.provider_code.lower()
    provider_name = config.provider_name.lower()
    base_url = config.base_url.lower()
    if "gemini" in provider_code or "google" in provider_code or "gemini" in provider_name or "generativelanguage.googleapis.com" in base_url:
        return "gemini"
    return "openai"


def _authorization_headers(config: GenerationModelConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {config.api_key}"
    else:
        headers["Authorization"] = config.api_key
    return headers


def _parse_provider_error_payload(error_body: str) -> tuple[str, str | None]:
    """从上游 JSON 抽出 error.message / error.code；抽不出则返回原文。"""
    text = str(error_body or "").strip()
    if not text:
        return "", None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text, None
    if not isinstance(payload, dict):
        return text, None

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        code = error.get("code")
        code_text = str(code).strip() if code is not None and str(code).strip() else None
        return message or text, code_text
    if isinstance(error, str) and error.strip():
        code = payload.get("code")
        code_text = str(code).strip() if code is not None and str(code).strip() else None
        return error.strip(), code_text

    detail = payload.get("detail")
    if isinstance(detail, dict):
        nested = detail.get("error")
        if isinstance(nested, dict):
            message = str(nested.get("message") or "").strip()
            code = nested.get("code")
            code_text = str(code).strip() if code is not None and str(code).strip() else None
            return message or text, code_text
        detail_message = str(detail.get("message") or detail.get("error") or "").strip()
        if detail_message:
            return detail_message, None
    if isinstance(detail, str) and detail.strip():
        return detail.strip(), None

    return text, None


def _is_gateway_timeout_error(status_code: int, message: str, error_code: str | None) -> bool:
    """
    超分统一出口超时：HTTP 400 + message「已超时」/ code timeout。
    仅这类应触发 image2 自动重试。
    """
    if int(status_code or 0) != 400:
        return False
    code = str(error_code or "").strip().lower()
    if code in {"timeout", "image_generation_timeout"}:
        return True
    text = str(message or "").strip()
    if not text:
        return False
    if text == MODEL_TIMEOUT_MESSAGE or "超时" in text:
        return True
    lower = text.lower()
    return (
        "timeout" in lower
        or "timed out" in lower
        or "deadline exceeded" in lower
    )


def _is_socket_timeout_error(exc: Exception) -> bool:
    """检测 socket 级超时（非 HTTP 超时，如 urlopen error timed out）。"""
    exc_type = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or exc_type.endswith(("timeout", "timeouterror")):
        return True
    lower = str(exc).lower()
    return (
        "timed out" in lower
        or "deadline exceeded" in lower
    )


def _is_transient_download_error(exc: Exception) -> bool:
    """Return whether a failed idempotent image GET is safe to retry."""
    if isinstance(exc, urllib.error.HTTPError):
        return int(exc.code or 0) in TRANSIENT_DOWNLOAD_HTTP_STATUS_CODES
    if isinstance(exc, ssl.SSLCertVerificationError):
        return False
    if _is_socket_timeout_error(exc):
        return True
    if isinstance(
        exc,
        (
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionRefusedError,
            ConnectionResetError,
            EOFError,
            http.client.BadStatusLine,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
            socket.gaierror,
            ssl.SSLError,
            urllib.error.ContentTooShortError,
        ),
    ):
        return True
    if isinstance(exc, OSError) and exc.errno in TRANSIENT_DOWNLOAD_ERRNOS:
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, Exception) and reason is not exc:
            return _is_transient_download_error(reason)
        reason_text = str(reason or "").lower()
        return any(
            marker in reason_text
            for marker in (
                "broken pipe",
                "connection aborted",
                "connection refused",
                "connection reset",
                "network is unreachable",
                "remote end closed",
                "temporary failure in name resolution",
                "tls",
            )
        )
    return False


def _is_safety_rejection(message: str, error_code: str | None = None) -> bool:
    """检测内容策略/安全审核拦截。"""
    code = str(error_code or "").strip().lower()
    if code in {
        "content_policy_violation",
        "content_filter",
        "safety",
        "blocked",
        "content_filter_triggered",
        "safety_ratings",
        "recitation",
    }:
        return True
    lower = str(message or "").lower()
    keywords = [
        "safety",
        "content policy",
        "content_policy",
        "content filter",
        "content_filter",
        "blocked",
        "inappropriate",
        "violation",
        "not allowed",
        "cannot generate",
        "can't generate",
        "unable to generate",
        "flagged",
        "harmful",
        "explicit",
        "sexual",
        "violence",
        "hate speech",
        "recitation",
        "your request was rejected",
        "does not comply",
        "doesn't comply",
    ]
    return any(kw in lower for kw in keywords)


def _is_image_capacity_error(message: str, error_code: str | None = None) -> bool:
    """Normalize upstream image quota/capacity wording without exposing vendor copy."""
    code = str(error_code or "").strip().lower()
    if code in {"image_quota_exhausted", "no_available_image_quota"}:
        return True
    text = str(message or "").strip().lower()
    return "no available image quota" in text or "image quota exhausted" in text


def _provider_error_message(status_code: int, error_body: str) -> tuple[str, int, int]:
    if status_code == 429:
        return MODEL_RATE_LIMIT_MESSAGE, 50229, 429

    message, error_code = _parse_provider_error_payload(error_body)

    # 400 + 超时 → 固定文案/业务码，供重试判断
    if _is_gateway_timeout_error(status_code, message, error_code):
        return MODEL_TIMEOUT_MESSAGE, MODEL_TIMEOUT_CODE, 400

    # 内容策略 / 安全审核拦截
    if _is_safety_rejection(message, error_code):
        return MODEL_SAFETY_REJECTED_MESSAGE, MODEL_SAFETY_CODE, 400

    # 上游的图片额度/容量错误属于暂时不可用，不向终端用户暴露供应商英文文案。
    if _is_image_capacity_error(message, error_code):
        return MODEL_IMAGE_CAPACITY_MESSAGE, 50230, 503

    # 其余：把上游 message 直接放出来，不重试
    if message:
        out_status = 400 if 400 <= int(status_code or 0) < 500 else 502
        # 内容策略等保持 400，便于下游区分「业务拒绝」与「服务异常」
        if int(status_code or 0) == 400:
            out_status = 400
        return message, 50212 if out_status == 400 else 50210, out_status

    return f"模型调用失败：HTTP {status_code} {str(error_body or '')[:300]}", 50210, 502


def _safe_provider_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _safe_request_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _safe_request_value(item) for key, item in value.items() if str(key).lower() not in {"api_key", "authorization", "token", "password", "secret"}}
    if isinstance(value, list):
        return [_safe_request_value(item) for item in value]
    if isinstance(value, str) and (value.startswith("data:") or len(value) > 4096):
        return {"redacted": "large_or_data_url", "length": len(value)}
    return value


def _attach_provider_trace(image: GeneratedImage, payload: dict) -> GeneratedImage:
    """Merge provider tracing from either `_image2_trace` or explicit top-level keys.

    Video success used to pass provider_request_id / snapshot at the top level, but this
    helper only read `_image2_trace`, so job ids never landed in the DB.
    """
    if not isinstance(payload, dict):
        return image
    trace = payload.get("_image2_trace") if isinstance(payload.get("_image2_trace"), dict) else {}

    provider_request_id = str(
        payload.get("provider_request_id")
        or trace.get("request_id")
        or payload.get("id")
        or payload.get("task_id")
        or payload.get("request_id")
        or image.provider_request_id
        or ""
    ).strip()

    snapshot = payload.get("provider_request_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = trace.get("request_snapshot") if isinstance(trace.get("request_snapshot"), dict) else None

    summary = payload.get("provider_response_summary")
    if not isinstance(summary, dict):
        summary = trace.get("response_summary") if isinstance(trace.get("response_summary"), dict) else None

    http_status = payload.get("provider_http_status")
    if not isinstance(http_status, int):
        http_status = trace.get("http_status") if isinstance(trace.get("http_status"), int) else image.provider_http_status

    return replace(
        image,
        provider_request_id=provider_request_id,
        provider_request_snapshot=snapshot if isinstance(snapshot, dict) else image.provider_request_snapshot,
        provider_response_summary=summary if isinstance(summary, dict) else image.provider_response_summary,
        provider_http_status=http_status if isinstance(http_status, int) else None,
    )


def _notify_model_completed(
    payload: dict,
    callback: Callable[[GeneratedImage], None] | None,
    *,
    deadline_monotonic: float,
) -> None:
    """Signal the exact boundary between upstream generation and result transfer."""
    _remaining_request_timeout(deadline_monotonic)
    if callback is None:
        return
    callback(
        _attach_provider_trace(
            GeneratedImage(content=b"", mime_type="application/octet-stream"),
            payload,
        )
    )


def _post_json(url: str, body: dict, headers: dict[str, str], timeout: int) -> dict:
    started_at = perf_counter()
    parsed_url = urllib.parse.urlparse(url)
    logged_url = urllib.parse.urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", "", ""))
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = _read_response_bytes(
                response,
                settings.image_provider_response_max_bytes,
                label="模型",
            )
            logger.warning(
                "image_provider_timing stage=post_json url=%s elapsed=%.3fs response_bytes=%s",
                logged_url,
                perf_counter() - started_at,
                len(response_body),
            )
            payload = json.loads(response_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise BusinessError("模型返回了无效响应", code=50215, status_code=502)
            request_id = str(response.headers.get("X-Request-ID") or payload.get("request_id") or "")
            payload["_image2_trace"] = {
                "request_id": request_id,
                "http_status": int(response.status),
                "request_snapshot": {"endpoint": _safe_provider_url(url), "body": _safe_request_value(body)},
                "response_summary": {"request_id": request_id, "top_level_keys": sorted(str(key) for key in payload if key != "_image2_trace"), "data_count": len(payload.get("data") or []), "output_count": len(payload.get("output") or [])},
            }
            return payload
    except urllib.error.HTTPError as exc:
        error_body = exc.read(1024).decode("utf-8", errors="replace")
        logger.warning(
            "image_provider_timing stage=post_json_failed url=%s elapsed=%.3fs http_status=%s error=%s",
            logged_url,
            perf_counter() - started_at,
            exc.code,
            error_body[:300],
        )
        message, code, status_code = _provider_error_message(exc.code, error_body)
        raise BusinessError(message, code=code, status_code=status_code) from exc
    except BusinessError:
        raise
    except Exception as exc:
        logger.warning(
            "image_provider_timing stage=post_json_failed url=%s elapsed=%.3fs error_type=%s error=%s",
            logged_url,
            perf_counter() - started_at,
            type(exc).__name__,
            str(exc)[:300],
        )
        if _is_socket_timeout_error(exc):
            raise BusinessError(MODEL_TIMEOUT_MESSAGE, code=MODEL_TIMEOUT_CODE, status_code=400) from exc
        raise BusinessError(f"模型调用失败：{exc}", code=50211, status_code=502) from exc


def _encode_multipart(fields: dict[str, str], files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    boundary = f"----image2ai{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, filename, mime_type, content in files:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _post_multipart(url: str, fields: dict[str, str], files: list[tuple[str, str, str, bytes]], config: GenerationModelConfig, timeout: int) -> dict:
    started_at = perf_counter()
    parsed_url = urllib.parse.urlparse(url)
    logged_url = urllib.parse.urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", "", ""))
    body, content_type = _encode_multipart(fields, files)
    headers = _authorization_headers(config)
    headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = _read_response_bytes(
                response,
                settings.image_provider_response_max_bytes,
                label="模型",
            )
            logger.warning(
                "image_provider_timing stage=post_multipart url=%s elapsed=%.3fs request_bytes=%s response_bytes=%s",
                logged_url,
                perf_counter() - started_at,
                len(body),
                len(response_body),
            )
            payload = json.loads(response_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise BusinessError("模型返回了无效响应", code=50215, status_code=502)
            request_id = str(response.headers.get("X-Request-ID") or payload.get("request_id") or "")
            payload["_image2_trace"] = {
                "request_id": request_id,
                "http_status": int(response.status),
                "request_snapshot": {"endpoint": _safe_provider_url(url), "fields": _safe_request_value(fields), "input_files": [{"field": name, "filename": filename, "mime_type": mime_type, "bytes": len(content)} for name, filename, mime_type, content in files]},
                "response_summary": {"request_id": request_id, "top_level_keys": sorted(str(key) for key in payload if key != "_image2_trace"), "data_count": len(payload.get("data") or [])},
            }
            return payload
    except urllib.error.HTTPError as exc:
        error_body = exc.read(1024).decode("utf-8", errors="replace")
        logger.warning(
            "image_provider_timing stage=post_multipart_failed url=%s elapsed=%.3fs request_bytes=%s http_status=%s error=%s",
            logged_url,
            perf_counter() - started_at,
            len(body),
            exc.code,
            error_body[:300],
        )
        message, code, status_code = _provider_error_message(exc.code, error_body)
        raise BusinessError(message, code=code, status_code=status_code) from exc
    except BusinessError:
        raise
    except Exception as exc:
        logger.warning(
            "image_provider_timing stage=post_multipart_failed url=%s elapsed=%.3fs request_bytes=%s error_type=%s error=%s",
            logged_url,
            perf_counter() - started_at,
            len(body),
            type(exc).__name__,
            str(exc)[:300],
        )
        if _is_socket_timeout_error(exc):
            raise BusinessError(MODEL_TIMEOUT_MESSAGE, code=MODEL_TIMEOUT_CODE, status_code=400) from exc
        raise BusinessError(f"模型调用失败：{exc}", code=50211, status_code=502) from exc


def _server_accessible_url(url: str) -> str:
    public_endpoint = settings.minio_public_endpoint.rstrip("/")
    internal_endpoint = f"http{'s' if settings.minio_secure else ''}://{settings.minio_endpoint}".rstrip("/")
    if public_endpoint and url.startswith(f"{public_endpoint}/"):
        return f"{internal_endpoint}/{url[len(public_endpoint):].lstrip('/')}"
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname in {"localhost", "127.0.0.1"} and parsed.port == 9000:
        return urllib.parse.urlunparse(parsed._replace(netloc=settings.minio_endpoint))
    return url


def _minio_input_fallback_url(url: str) -> str | None:
    """Map our Qiniu object URL to its durable MinIO mirror, if available."""
    qiniu_base = (settings.qiniu_cdn_base_url or "").strip().rstrip("/")
    minio_base = (settings.minio_public_endpoint or "").strip().rstrip("/")
    if not qiniu_base or not minio_base or not url.startswith(f"{qiniu_base}/"):
        return None
    return f"{minio_base}{url[len(qiniu_base):]}"


def _r2_hot_url_candidate(url: str | None) -> str | None:
    value = (url or "").strip()
    if not value.startswith(("http://", "https://")):
        return None
    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").lower()
    configured_base = (settings.r2_public_base_url or "").strip().rstrip("/")
    if configured_base and value.startswith(f"{configured_base}/"):
        return value
    if host.endswith(".r2.dev") or host.endswith(".r2.cloudflarestorage.com"):
        return value
    return None


def _download_image_prefer_hot(
    primary_url: str,
    timeout: int | float,
    *,
    fallback_url: str | None = None,
) -> tuple[GeneratedImage, bool]:
    try:
        return _download_image(primary_url, timeout), True
    except BusinessError:
        fallback = (fallback_url or "").strip()
        if not fallback or fallback == primary_url:
            raise
        logger.warning(
            "image_provider_timing stage=hot_url_fallback primary=%s fallback=%s",
            _safe_provider_url(primary_url),
            _safe_provider_url(fallback),
        )
        # Do not advertise an R2 hot URL that was already unreachable during
        # generation. The local copy remains the guaranteed result.
        return replace(_download_image(fallback, timeout), hot_url=None), False


def _download_image(
    url: str,
    timeout: int | float | None = None,
    *,
    download_kind: DownloadKind = "result",
) -> GeneratedImage:
    started_at = perf_counter()
    download_url = _server_accessible_url(url)
    parsed_url = urllib.parse.urlparse(download_url)
    logged_url = urllib.parse.urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", "", ""))
    total_timeout = max(
        0.05,
        float(timeout if timeout is not None else settings.image_result_download_timeout_seconds),
    )
    deadline = started_at + total_timeout
    max_attempts = max(1, int(settings.image_download_retry_attempts))
    timeout_code = INPUT_DOWNLOAD_TIMEOUT_CODE if download_kind == "input" else RESULT_DOWNLOAD_TIMEOUT_CODE
    timeout_message = INPUT_DOWNLOAD_TIMEOUT_MESSAGE if download_kind == "input" else RESULT_DOWNLOAD_TIMEOUT_MESSAGE
    failed_code = INPUT_DOWNLOAD_FAILED_CODE if download_kind == "input" else RESULT_DOWNLOAD_FAILED_CODE
    failed_message = INPUT_DOWNLOAD_FAILED_MESSAGE if download_kind == "input" else RESULT_DOWNLOAD_FAILED_MESSAGE
    file_label = "输入原图" if download_kind == "input" else "模型结果"
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        remaining = deadline - perf_counter()
        if remaining <= 0:
            raise BusinessError(timeout_message, code=timeout_code, status_code=504) from last_error
        request = urllib.request.Request(
            download_url,
            headers={"User-Agent": "image2-user-server/1.0"},
            method="GET",
        )
        transfer_started = perf_counter()
        read_timeout = min(
            max(0.05, float(settings.image_result_download_read_timeout_seconds)),
            remaining,
        )
        try:
            with urllib.request.urlopen(request, timeout=read_timeout) as response:
                content_type = response.headers.get("Content-Type", "image/png").split(";")[0].strip()
                content_length = response.headers.get("Content-Length")
                max_bytes = max(1, int(settings.image_result_download_max_bytes))
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise BusinessError(
                                f"{file_label}文件过大，最大允许 {max_bytes // (1024 * 1024)}MB",
                                code=50234,
                                status_code=502,
                            )
                    except ValueError:
                        pass
                content_buffer = bytearray()
                while True:
                    if perf_counter() >= deadline:
                        raise BusinessError(
                            timeout_message,
                            code=timeout_code,
                            status_code=504,
                        )
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    content_buffer.extend(chunk)
                    if len(content_buffer) > max_bytes:
                        raise BusinessError(
                            f"{file_label}文件过大，最大允许 {max_bytes // (1024 * 1024)}MB",
                            code=50234,
                            status_code=502,
                        )
                content = bytes(content_buffer)
            logger.warning(
                "image_provider_timing stage=download_image url=%s elapsed=%.3fs "
                "transfer=%.3fs bytes=%s mime_type=%s download_kind=%s attempt=%s",
                logged_url,
                perf_counter() - started_at,
                perf_counter() - transfer_started,
                len(content),
                content_type,
                download_kind,
                attempt,
            )
            return GeneratedImage(
                content=content,
                mime_type=content_type,
                hot_url=_r2_hot_url_candidate(url),
            )
        except BusinessError:
            raise
        except Exception as exc:
            last_error = exc
            transient = _is_transient_download_error(exc)
            remaining = deadline - perf_counter()
            should_retry = transient and attempt < max_attempts and remaining > 0
            logger.warning(
                "image_provider_timing stage=download_image_attempt_failed url=%s elapsed=%.3fs "
                "download_kind=%s attempt=%s max_attempts=%s retry=%s error_type=%s error=%s",
                logged_url,
                perf_counter() - started_at,
                download_kind,
                attempt,
                max_attempts,
                should_retry,
                type(exc).__name__,
                str(exc)[:300],
            )
            if should_retry:
                retry_delay = min(
                    max(0.0, float(settings.image_download_retry_delay_seconds)) * (2 ** (attempt - 1)),
                    max(0.0, deadline - perf_counter()),
                )
                if retry_delay > 0:
                    sleep(retry_delay)
                continue
            logger.warning(
                "image_provider_timing stage=download_image_failed url=%s elapsed=%.3fs "
                "download_kind=%s attempts=%s transient=%s error_type=%s error=%s",
                logged_url,
                perf_counter() - started_at,
                download_kind,
                attempt,
                transient,
                type(exc).__name__,
                str(exc)[:300],
            )
            if _is_socket_timeout_error(exc):
                raise BusinessError(timeout_message, code=timeout_code, status_code=504) from exc
            if transient:
                raise BusinessError(failed_message, code=failed_code, status_code=502) from exc
            raise BusinessError(f"{failed_message}：{exc}", code=failed_code, status_code=502) from exc

    raise BusinessError(failed_message, code=failed_code, status_code=502) from last_error


def _decode_base64_image(value: str, default_mime_type: str = "image/png") -> GeneratedImage:
    mime_type = default_mime_type
    payload = value
    if value.startswith("data:"):
        header, _, payload = value.partition(",")
        if ";" in header:
            mime_type = header[5:].split(";")[0] or default_mime_type
    try:
        return GeneratedImage(content=base64.b64decode(payload), mime_type=mime_type)
    except Exception as exc:
        raise BusinessError("模型返回的图片数据无法解码", code=50213, status_code=502) from exc


def _image_from_text_value(value: str, timeout: int) -> GeneratedImage | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return _download_image(stripped, timeout)
    if stripped.startswith("data:image/"):
        return _decode_base64_image(stripped)

    markdown_match = re.search(r"!\[[^\]]*]\(([^)\s]+)\)", stripped)
    if markdown_match:
        image_value = markdown_match.group(1)
        if image_value.startswith("http://") or image_value.startswith("https://"):
            return _download_image(image_value, timeout)
        if image_value.startswith("data:image/"):
            return _decode_base64_image(image_value)

    data_url_match = re.search(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\r\n]+", stripped)
    if data_url_match:
        return _decode_base64_image(data_url_match.group(0))
    return None


def _extract_openai_images_result(payload: dict, timeout: int) -> GeneratedImage:
    for item in payload.get("data") or []:
        hot_url = str(item.get("r2_url") or "").strip() or _r2_hot_url_candidate(item.get("url"))
        download_url = hot_url or item.get("url")
        if download_url:
            logger.warning(
                "image_provider_timing stage=openai_image_result has_url=true has_r2_url=%s has_b64=%s b64_chars=%s",
                bool(hot_url),
                bool(item.get("b64_json")),
                len(item.get("b64_json") or ""),
            )
            image, hot_available = _download_image_prefer_hot(
                download_url,
                timeout,
                fallback_url=item.get("url") if hot_url else None,
            )
            return replace(image, hot_url=hot_url if hot_available else image.hot_url)
        if item.get("b64_json"):
            logger.warning(
                "image_provider_timing stage=openai_image_result has_url=false has_b64=true b64_chars=%s",
                len(item["b64_json"]),
            )
            return _decode_base64_image(item["b64_json"])
    raise BusinessError("模型未返回图片结果", code=50214, status_code=502)


def _extract_responses_image_result(payload: dict, timeout: int) -> GeneratedImage:
    for item in payload.get("output") or []:
        if item.get("type") == "image_generation_call":
            if item.get("result"):
                return _decode_base64_image(item["result"])
            hot_url = str(item.get("r2_url") or "").strip() or _r2_hot_url_candidate(item.get("url"))
            download_url = hot_url or item.get("url")
            if download_url:
                image = _download_image(download_url, timeout)
                return replace(image, hot_url=hot_url or image.hot_url)
    raise BusinessError("模型未返回图片结果", code=50214, status_code=502)


def _extract_gemini_image_result(payload: dict) -> GeneratedImage:
    for candidate in payload.get("candidates") or []:
        for part in ((candidate.get("content") or {}).get("parts") or []):
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                return _decode_base64_image(inline_data["data"], inline_data.get("mimeType") or inline_data.get("mime_type") or "image/png")
    raise BusinessError("模型未返回图片结果", code=50214, status_code=502)



OPENAI_IMAGES_API_MODEL_PREFIXES = (
    "gpt-image",
    "grok-imagine-image",
    "agent5-gpt-image",
    "agent5-nano-banana",
    "firefly-gpt-image",
    "firefly-nano-banana",
)


def _uses_openai_images_api(vendor_model: str) -> bool:
    """Return whether a model uses the OpenAI-compatible Images API."""
    model = (vendor_model or "").strip().lower()
    return model.startswith(OPENAI_IMAGES_API_MODEL_PREFIXES)


def _openai_images_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/images/generations"
    return f"{normalized}/v1/images/generations"


def _openai_image_edits_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/images/edits"
    return f"{normalized}/v1/images/edits"


def _openai_responses_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/responses"
    return f"{normalized}/v1/responses"


def _openai_chat_completions_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _gemini_endpoint(base_url: str, vendor_model: str, api_key: str) -> str:
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1") and not normalized.endswith("/v1beta"):
        normalized = f"{normalized}/v1beta"
    return f"{normalized}/models/{urllib.parse.quote(vendor_model, safe='')}:generateContent?key={urllib.parse.quote(api_key, safe='')}"


def _gemini_generation_config(vendor_model: str, resolution: str, aspect_ratio: str) -> dict:
    config: dict = {"responseModalities": ["TEXT", "IMAGE"]}
    model = vendor_model.strip().lower().removeprefix("models/")
    # These native image models accept structured output dimensions. Keep
    # unrelated Gemini models on their existing request contract.
    basic = model in {"gemini-2.5-flash-image", "gemini-2.5-flash-image-preview"}
    # agent5 exposes Banana 2 under the nano-banana alias.
    sized = model in {"nano-banana", "nano-banana-pro"} or model.startswith(("gemini-3-pro-image", "gemini-3.1-flash-image"))
    if not (basic or sized):
        return config
    image_config: dict = {}
    if aspect_ratio in {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}:
        image_config["aspectRatio"] = aspect_ratio
    if sized and resolution.lower() in {"1k", "2k", "4k"}:
        image_config["imageSize"] = resolution.upper()
    if image_config:
        config["imageConfig"] = image_config
    return config


def _image_filename(mime_type: str, index: int = 0) -> str:
    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(mime_type, "png")
    return f"input-{index + 1}.{extension}"


def _input_image_from_value(value: str | None, timeout: int) -> GeneratedImage | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    if normalized.startswith("data:"):
        return _decode_base64_image(normalized)
    if normalized.startswith("/"):
        raise BusinessError("输入图片必须是 MinIO 公开地址或 data URL", code=40024, status_code=400)
    if normalized.startswith("http://") or normalized.startswith("https://"):
        try:
            # CDN is the primary input source. Download it here and attach the
            # resulting bytes to the provider request; the provider never has
            # to reach Qiniu directly.
            return _download_image(normalized, timeout, download_kind="input")
        except BusinessError as primary_error:
            fallback_url = _minio_input_fallback_url(normalized)
            if not fallback_url or fallback_url == normalized:
                raise
            logger.warning(
                "image_provider_timing stage=input_minio_fallback primary=%s fallback=%s",
                _safe_provider_url(normalized),
                _safe_provider_url(fallback_url),
            )
            try:
                return _download_image(fallback_url, timeout, download_kind="input")
            except BusinessError:
                raise primary_error
    return _decode_base64_image(normalized)


def _input_images_from_values(
    values: str | list[str] | tuple[str, ...] | None,
    timeout: int | float,
    *,
    deadline_monotonic: float | None = None,
) -> list[GeneratedImage]:
    if values is None:
        return []
    if isinstance(values, str):
        value_list = [values]
    else:
        value_list = list(values)
    images: list[GeneratedImage] = []
    for value in value_list:
        request_timeout = _remaining_request_timeout(deadline_monotonic) if deadline_monotonic is not None else timeout
        image = _input_image_from_value(value, request_timeout)
        if image is not None:
            images.append(image)
    return images


def _openai_image_edit_files(source_images: list[GeneratedImage]) -> list[tuple[str, str, str, bytes]]:
    return [
        ("image", _image_filename(source_image.mime_type, index), source_image.mime_type, source_image.content)
        for index, source_image in enumerate(source_images)
    ]


def _data_url_from_image(image: GeneratedImage) -> str:
    encoded = base64.b64encode(image.content).decode("ascii")
    return f"data:{image.mime_type};base64,{encoded}"


def _generation_prompt(prompt: str, resolution: str, aspect_ratio: str, has_input_image: bool = False) -> str:
    constraints = []
    if resolution and resolution.strip().lower() != "auto":
        constraints.append(f"分辨率：{resolution}")
    if aspect_ratio and aspect_ratio.strip().lower() != "auto":
        constraints.append(f"画面比例：{aspect_ratio}")
    parameter_instruction = ""
    if constraints:
        parameter_instruction = f"\n\n生成参数要求：{'; '.join(constraints)}。请严格按照分辨率档位和画面比例输出。"
    if has_input_image:
        return f"{IMAGE_EDIT_INSTRUCTION}\n\n用户修改要求：{prompt}{parameter_instruction}"
    return f"{prompt}{parameter_instruction}"


def _prompt_with_image_reference_map(prompt: str, image_count: int) -> str:
    if image_count <= 0:
        return prompt
    reference_lines = "\n".join(f"- @图片 {index} / @图片{index}：第 {index} 张输入图片" for index in range(1, image_count + 1))
    return (
        "图片引用说明：用户提示词中的图片引用按输入图片顺序对应如下。"
        "当用户提到某个 @图片 编号时，请只把该编号对应的输入图片作为该描述的主体或参考。\n"
        f"{reference_lines}\n\n"
        f"用户原始提示词：{prompt}"
    )


def _openai_size(resolution: str, aspect_ratio: str) -> str:
    if "auto" in {resolution.strip().lower(), aspect_ratio.strip().lower()}:
        return "auto"
    # Keep public rectangles on provider-supported presets. Adobe also requires
    # both GPT Image edges to be multiples of 16, so A-series ratios use the
    # closest aligned approximation at each resolution.
    sizes = {
        "720p": {
            "1:1": "720x720",
            "4:3": "960x720",
            "3:4": "720x960",
            "16:9": "1280x720",
            "9:16": "720x1280",
            "3:2": "1080x720",
            "2:3": "720x1080",
            "21:9": "1680x720",
        },
        "1k": {
            "1:1": "1024x1024",
            "1:1.414": "1024x1440",
            "1.414:1": "1440x1024",
            "4:3": "1152x864",
            "3:4": "864x1152",
            "16:9": "1536x864",
            "9:16": "864x1536",
            "3:2": "1536x1024",
            "2:3": "1024x1536",
            "21:9": "1792x768",
        },
        "2k": {
            "1:1": "2048x2048",
            "1:1.414": "1456x2048",
            "1.414:1": "2048x1456",
            "4:3": "2048x1536",
            "3:4": "1536x2048",
            "16:9": "2048x1152",
            "9:16": "1152x2048",
            "3:2": "2016x1344",
            "2:3": "1344x2016",
            "21:9": "2016x864",
        },
        "4k": {
            "1:1": "3840x3840",
            "1:1.414": "2720x3840",
            "1.414:1": "3840x2720",
            "4:3": "3840x2880",
            "3:4": "2880x3840",
            "16:9": "3840x2160",
            "9:16": "2160x3840",
            "3:2": "3840x2560",
            "2:3": "2560x3840",
            "21:9": "3696x1584",
        },
    }
    resolution_sizes = sizes.get(resolution) or sizes["1k"]
    return resolution_sizes.get(aspect_ratio) or resolution_sizes["1:1"]


def _resolution_pixels(resolution: str) -> int | None:
    return {
        "720p": 720,
        "1k": 1024,
        "2k": 2048,
        "4k": 4096,
    }.get(resolution)


def _aspect_ratio_dimensions(resolution: str, aspect_ratio: str) -> tuple[int, int] | None:
    pixels = _resolution_pixels(resolution)
    if not pixels:
        return None
    ratios = {
        "1:1": (1, 1),
        "1:1.414": (500, 707),
        "1.414:1": (707, 500),
        "4:3": (4, 3),
        "3:4": (3, 4),
        "16:9": (16, 9),
        "9:16": (9, 16),
        "3:2": (3, 2),
        "2:3": (2, 3),
        "21:9": (21, 9),
    }
    ratio = ratios.get(aspect_ratio)
    if not ratio:
        return pixels, pixels
    width_ratio, height_ratio = ratio
    if width_ratio >= height_ratio:
        return pixels, max(1, round(pixels * height_ratio / width_ratio))
    return max(1, round(pixels * width_ratio / height_ratio)), pixels


def _openai_chat_completions_body(config: GenerationModelConfig, content: str | list[dict], resolution: str, aspect_ratio: str) -> dict:
    body: dict = {
        "model": config.vendor_model,
        "messages": [{"role": "user", "content": content}],
    }
    if _uses_openai_images_api(config.vendor_model) and "auto" in {resolution.strip().lower(), aspect_ratio.strip().lower()}:
        body["size"] = "auto"
        return body
    if aspect_ratio and aspect_ratio.strip().lower() != "auto":
        body["aspect_ratio"] = aspect_ratio
    dimensions = _aspect_ratio_dimensions(resolution, aspect_ratio)
    if dimensions:
        body["width"], body["height"] = dimensions
    return body


def _extract_chat_completions_image_result(payload: dict, timeout: int) -> GeneratedImage:
    for choice in payload.get("choices") or []:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            image = _image_from_text_value(content, timeout)
            if image:
                return image
            try:
                parsed = json.loads(content.strip())
                if isinstance(parsed, dict):
                    image_value = parsed.get("r2_url") or parsed.get("url") or parsed.get("image_url") or parsed.get("b64_json") or parsed.get("base64")
                    if isinstance(image_value, str):
                        image = _image_from_text_value(image_value, timeout)
                        if image:
                            return image
                        return _decode_base64_image(image_value)
            except json.JSONDecodeError:
                pass
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                image_url = (part.get("image_url") or {}).get("url") if isinstance(part.get("image_url"), dict) else part.get("image_url")
                if isinstance(image_url, str):
                    image = _image_from_text_value(image_url, timeout)
                    if image:
                        return image
                    return _decode_base64_image(image_url)
    raise BusinessError("SDK 接入未返回可识别的图片结果", code=50214, status_code=502)


def generate_image(
    config: GenerationModelConfig,
    prompt: str,
    input_image: str | list[str] | None = None,
    resolution: str = "",
    aspect_ratio: str = "",
    *,
    quality: str = "auto",
    client_reference: str = "",
    on_model_started: Callable[[], None] | None = None,
    on_model_completed: Callable[[GeneratedImage], None] | None = None,
) -> GeneratedImage:
    if not config.api_key.strip():
        raise BusinessError("模型供应商 API Key 为空", code=50201, status_code=502)
    quality = normalize_image_quality(quality)
    source_images = _input_images_from_values(
        input_image,
        settings.image_result_download_timeout_seconds,
    )
    # 模型 deadline 从真正发起上游生成请求时开始。输入/结果文件传输均使用
    # 独立的下载预算，不能挤占模型生成时间。
    if on_model_started is not None:
        on_model_started()
    deadline_monotonic = _request_deadline_monotonic(config.timeout_seconds)
    provider_kind = _provider_kind(config)
    uses_images_api = _uses_openai_images_api(config.vendor_model)
    if uses_images_api:
        # The upstream Images API owns image parameters. Keep the user prompt
        # opaque and pass size/quality as structured fields below.
        final_prompt = prompt
    else:
        prompt_for_generation = _prompt_with_image_reference_map(prompt, len(source_images))
        final_prompt = _generation_prompt(prompt_for_generation, resolution, aspect_ratio, bool(source_images))
    if provider_kind == "openai_chat_completions":
        content: str | list[dict] = final_prompt
        if source_images:
            content = [{"type": "text", "text": final_prompt}]
            content.extend({"type": "image_url", "image_url": {"url": _data_url_from_image(image)}} for image in source_images)
        payload = _post_json(
            _openai_chat_completions_endpoint(config.base_url),
            _openai_chat_completions_body(config, content, resolution, aspect_ratio),
            _authorization_headers(config),
            _remaining_request_timeout(deadline_monotonic),
        )
        _notify_model_completed(payload, on_model_completed, deadline_monotonic=deadline_monotonic)
        return _attach_provider_trace(
            _extract_chat_completions_image_result(payload, settings.image_result_download_timeout_seconds),
            payload,
        )

    if provider_kind == "gemini":
        parts: list[dict] = [{"text": final_prompt}]
        for source_image in source_images:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": source_image.mime_type,
                        "data": base64.b64encode(source_image.content).decode("ascii"),
                    }
                }
            )
        payload = _post_json(
            _gemini_endpoint(config.base_url, config.vendor_model, config.api_key),
            {
                "contents": [{"parts": parts}],
                "generationConfig": _gemini_generation_config(config.vendor_model, resolution, aspect_ratio),
            },
            {"Content-Type": "application/json"},
            _remaining_request_timeout(deadline_monotonic),
        )
        _notify_model_completed(payload, on_model_completed, deadline_monotonic=deadline_monotonic)
        return _attach_provider_trace(_extract_gemini_image_result(payload), payload)

    if uses_images_api:
        size = _openai_size(resolution, aspect_ratio)
        common_fields: dict[str, str] = {
            "model": config.vendor_model,
            "prompt": final_prompt,
            "size": size,
            "quality": quality,
        }
        normalized_client_reference = str(client_reference or "").strip()
        if normalized_client_reference:
            common_fields["client_reference"] = normalized_client_reference
        if source_images:
            payload = _post_multipart(
                _openai_image_edits_endpoint(config.base_url),
                common_fields,
                _openai_image_edit_files(source_images),
                config,
                _remaining_request_timeout(deadline_monotonic),
            )
            _notify_model_completed(payload, on_model_completed, deadline_monotonic=deadline_monotonic)
            return _attach_provider_trace(
                _extract_openai_images_result(payload, settings.image_result_download_timeout_seconds),
                payload,
            )
        payload = _post_json(
            _openai_images_endpoint(config.base_url),
            common_fields,
            _authorization_headers(config),
            _remaining_request_timeout(deadline_monotonic),
        )
        _notify_model_completed(payload, on_model_completed, deadline_monotonic=deadline_monotonic)
        return _attach_provider_trace(
            _extract_openai_images_result(payload, settings.image_result_download_timeout_seconds),
            payload,
        )

    response_input: str | list[dict] = final_prompt
    if source_images:
        response_input = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": final_prompt}]
                + [{"type": "input_image", "image_url": _data_url_from_image(image)} for image in source_images],
            }
        ]
    payload = _post_json(
        _openai_responses_endpoint(config.base_url),
        {
            "model": config.vendor_model,
            "input": response_input,
            "tools": [{"type": "image_generation", "quality": quality}],
            "tool_choice": "auto",
        },
        _authorization_headers(config),
        _remaining_request_timeout(deadline_monotonic),
    )
    _notify_model_completed(payload, on_model_completed, deadline_monotonic=deadline_monotonic)
    return _attach_provider_trace(
        _extract_responses_image_result(payload, settings.image_result_download_timeout_seconds),
        payload,
    )


def _guess_media_mime_from_url(url: str, default: str = "video/mp4") -> str:
    lower = (url or "").lower().split("?", 1)[0]
    if lower.endswith(".webm"):
        return "video/webm"
    if lower.endswith(".mov"):
        return "video/quicktime"
    if lower.endswith(".m4v"):
        return "video/x-m4v"
    if lower.endswith((".mp4", ".mpeg", ".mpg")):
        return "video/mp4"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return default


def _extract_media_url(payload: object) -> str | None:
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith(("http://", "https://", "data:")):
            return text
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _extract_media_url(item)
            if found:
                return found
        return None
    if not isinstance(payload, dict):
        return None

    for key in (
        "video_url",
        "content_url",
        "url",
        "output_url",
        "result_url",
        "file_url",
        "download_url",
        "media_url",
        "uri",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("video", "data", "output", "outputs", "results", "videos", "choices", "items", "message", "content"):
        if key in payload:
            found = _extract_media_url(payload.get(key))
            if found:
                return found
    return None


def _resolve_video_media_url(
    media_url: str,
    *,
    poll_url: str = "",
    create_endpoint: str = "",
    prefer_task_content: bool = False,
) -> str:
    """Resolve Adobe/NewAPI video results through the authenticated task proxy."""
    value = str(media_url or "").strip()
    if not value or value.startswith("data:"):
        return value

    normalized_poll_url = str(poll_url or "").strip()
    if prefer_task_content and normalized_poll_url:
        parsed_poll_url = urllib.parse.urlsplit(normalized_poll_url)
        if re.search(r"/videos/[^/]+$", parsed_poll_url.path.rstrip("/")):
            return urllib.parse.urlunsplit(
                parsed_poll_url._replace(
                    path=f"{parsed_poll_url.path.rstrip('/')}/content",
                    query="",
                    fragment="",
                )
            )

    if value.startswith(("http://", "https://")):
        return value
    if create_endpoint:
        return urllib.parse.urljoin(f"{create_endpoint.rstrip('/')}/", value)
    return value


def uses_adobe_video_contract(vendor_model: str) -> bool:
    model = str(vendor_model or "").strip().lower()
    return model.startswith(ADOBE_VIDEO_MODEL_PREFIXES)


def _video_endpoint_candidates(base_url: str) -> list[str]:
    """Build video create endpoints for OpenAI/xAI-compatible gateways.

    Providers may store base_url as host only (https://cpa.example) or with /v1.
    CLIProxyAPI/xAI expect /v1/videos/generations (or /v1/videos).
    """
    normalized = (base_url or "").rstrip("/")
    if not normalized:
        return []
    roots: list[str] = []
    if normalized.endswith("/v1"):
        roots.append(normalized)
    else:
        roots.extend([f"{normalized}/v1", normalized])
    candidates: list[str] = []
    for root in roots:
        candidates.extend(
            [
                f"{root}/videos/generations",
                f"{root}/videos",
                f"{root}/video/generations",
                f"{root}/video/create",
            ]
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _video_poll_url_candidates(create_endpoint: str, job_id: str) -> list[str]:
    """Poll URLs for async video jobs (xAI/CLIProxy: GET /v1/videos/{request_id})."""
    endpoint = (create_endpoint or "").rstrip("/")
    job = urllib.parse.quote(str(job_id or "").strip(), safe="")
    if not endpoint or not job:
        return []

    roots: list[str] = []
    for marker in (
        "/videos/generations",
        "/video/generations",
        "/video/create",
        "/videos",
    ):
        idx = endpoint.rfind(marker)
        if idx >= 0:
            roots.append(endpoint[:idx])
            break
    else:
        roots.append(endpoint.rsplit("/", 1)[0] if "/" in endpoint else endpoint)

    expanded: list[str] = []
    for root in roots:
        root = root.rstrip("/")
        if not root:
            continue
        expanded.append(root)
        if root.endswith("/v1"):
            parent = root[: -len("/v1")].rstrip("/")
            if parent:
                expanded.append(parent)
        else:
            expanded.append(f"{root}/v1")

    # Prefer /v1/videos/{id} (CLIProxy/xAI) before /videos/generations/{id}.
    candidates: list[str] = []
    for root in expanded:
        candidates.append(f"{root}/videos/{job}")
        if not root.endswith("/v1"):
            candidates.append(f"{root}/v1/videos/{job}")
    candidates.append(f"{endpoint}/{job}")

    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _parse_duration_seconds(duration_code: str) -> int | None:
    text = (duration_code or "").strip().lower()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    return value if value > 0 else None


def is_duration_code(value: str | None) -> bool:
    """True when value looks like a video duration code (e.g. 6 / 6s / 10), not a ratio."""
    text = (value or "").strip().lower()
    if not text or ":" in text or "|" in text:
        return False
    cleaned = text.replace("s", "").replace(" ", "")
    return cleaned.isdigit() and int(cleaned) > 0


def pack_video_task_aspect(ratio: str | None, duration: str | None) -> str:
    """Persist real aspect ratio + duration in image_tasks.aspect_ratio as `ratio|duration`."""
    ratio_text = (ratio or "").strip()
    duration_text = (duration or "").strip()
    if duration_text and is_duration_code(duration_text):
        if ratio_text and not is_duration_code(ratio_text):
            return f"{ratio_text}|{duration_text}"
        # Legacy clients may only send duration via aspect_ratio.
        return f"16:9|{duration_text}"
    if ratio_text and is_duration_code(ratio_text):
        return f"16:9|{ratio_text}"
    return ratio_text or "16:9"


def unpack_video_task_aspect(value: str | None) -> tuple[str, str]:
    """Return (aspect_ratio, duration_code) from packed task field."""
    text = (value or "").strip()
    if not text:
        return "16:9", ""
    if "|" in text:
        left, right = text.split("|", 1)
        ratio = left.strip() or "16:9"
        duration = right.strip()
        return ratio, duration
    if is_duration_code(text):
        return "16:9", text
    return text, ""


def _video_image_ref(image: GeneratedImage) -> str:
    """Prefer provider-hosted HTTP(S) URL; fall back to data URL for local bytes."""
    image_ref = (image.source_url or "").strip()
    if image_ref.startswith("http://") or image_ref.startswith("https://"):
        return image_ref
    return _data_url_from_image(image)


def _normalize_video_duration_seconds(duration_code: str) -> int | None:
    """Parse and hard-validate official xAI duration range [1, 15]."""
    duration = _parse_duration_seconds(duration_code)
    if duration is None:
        return None
    if duration < 1 or duration > 15:
        raise BusinessError(
            f"视频时长需在 1–15 秒之间，当前为 {duration} 秒",
            code=40001,
            status_code=400,
        )
    return duration


def _normalize_video_resolution(resolution: str) -> str:
    text = (resolution or "").strip().lower()
    if not text:
        return ""
    # Accept WxH only when already pixel size; map common labels to official values.
    if text in {"480p", "720p", "1080p"}:
        return text
    size_to_label = {
        "854x480": "480p",
        "640x480": "480p",
        "1280x720": "720p",
        "1920x1080": "1080p",
    }
    return size_to_label.get(text, text if text.endswith("p") else "")


def _video_request_bodies(
    config: GenerationModelConfig,
    prompt: str,
    resolution: str,
    duration_code: str,
    source_images: list[GeneratedImage],
    aspect_ratio: str = "",
    user: str = "",
) -> list[dict]:
    """Build create payloads for video generation.

    Strategy:
    1. Official xAI body first (`duration` + `resolution` + `image`/`reference_images`)
    2. Limited compatibility fallbacks (never send both `duration` and `seconds`)
    Multi-image B: first image → `image`, remaining → `reference_images`.
    """
    duration = _normalize_video_duration_seconds(duration_code)
    ratio = (aspect_ratio or "").strip()
    if ratio and is_duration_code(ratio):
        ratio = ""
    official_resolution = _normalize_video_resolution(resolution)
    user_id = (user or "").strip()

    official: dict = {
        "model": config.vendor_model,
        "prompt": prompt,
    }
    if ratio:
        official["aspect_ratio"] = ratio
    if official_resolution:
        official["resolution"] = official_resolution
    if duration is not None:
        official["duration"] = duration
    if user_id:
        official["user"] = user_id

    adobe_video_contract = uses_adobe_video_contract(config.vendor_model)
    if len(source_images) == 1:
        image_ref = _video_image_ref(source_images[0])
        official["image"] = (
            image_ref if adobe_video_contract else {"url": image_ref}
        )
    elif len(source_images) > 1:
        image_refs = [_video_image_ref(image) for image in source_images]
        if adobe_video_contract:
            # NewAPI's task schema and adobe2api both recognize repeated
            # references under `images`; xAI uses `reference_images`.
            official["images"] = image_refs
        else:
            official["image"] = {"url": image_refs[0]}
            official["reference_images"] = [
                {"url": image_ref} for image_ref in image_refs[1:]
            ]

    bodies: list[dict] = []
    seen: set[str] = set()

    def _add(item: dict) -> None:
        # Never allow both duration aliases in one body.
        if "duration" in item and "seconds" in item:
            item = {k: v for k, v in item.items() if k != "seconds"}
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key in seen:
            return
        seen.add(key)
        bodies.append(item)

    # 1) Official-first
    _add(official)

    # 2) Compatibility: image as plain URL string (some gateways)
    if source_images and isinstance(official.get("image"), dict):
        first_ref = official["image"]["url"]
        plain_image = {k: v for k, v in official.items() if k != "image"}
        plain_image["image"] = first_ref
        _add(plain_image)

    # 3) Compatibility: OpenAI-style `seconds` instead of `duration` (never both)
    if duration is not None:
        seconds_body = {k: v for k, v in official.items() if k != "duration"}
        seconds_body["seconds"] = str(duration)
        _add(seconds_body)

    # Preserve the existing single-reference compatibility fallback for
    # providers that reject repeated xAI reference fields.
    if official.get("reference_images"):
        single_only = {k: v for k, v in official.items() if k != "reference_images"}
        _add(single_only)

    return bodies


def _download_video(
    url: str,
    timeout: int | float,
    request_headers: dict[str, str] | None = None,
) -> GeneratedImage:
    headers = {"User-Agent": "image2-user-server/1.0"}
    for key, value in (request_headers or {}).items():
        if key.lower() in {"authorization", "x-api-key"}:
            headers[key] = value
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = _read_response_bytes(
                response,
                settings.image_video_download_max_bytes,
                label="生成视频",
            )
            mime_type = (response.headers.get_content_type() or "").strip() or _guess_media_mime_from_url(url)
    except BusinessError:
        raise
    except Exception as exc:  # noqa: BLE001
        if _is_socket_timeout_error(exc):
            raise BusinessError(MODEL_TIMEOUT_MESSAGE, code=MODEL_TIMEOUT_CODE, status_code=400) from exc
        raise BusinessError(f"下载生成视频失败: {exc}", code=50220, status_code=502) from exc
    if not content:
        raise BusinessError("下载生成视频为空", code=50221, status_code=502)
    return GeneratedImage(content=content, mime_type=mime_type or "video/mp4", source_url=url)


def _poll_video_job(
    poll_url: str,
    headers: dict[str, str],
    timeout: int | float,
    *,
    deadline_monotonic: float | None = None,
) -> dict | None:
    import time as _time

    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    transport_errors = 0
    # Shared deadline across poll URL candidates so we don't burn timeout repeatedly.
    poll_budget = max(0.05, float(timeout or DEFAULT_MODEL_TASK_TIMEOUT_SECONDS))
    deadline = float(deadline_monotonic) if deadline_monotonic is not None else (_time.monotonic() + poll_budget)
    if deadline <= _time.monotonic():
        return None
    while _time.monotonic() < deadline:
        request = urllib.request.Request(poll_url, headers=get_headers)
        try:
            request_timeout = min(30.0, max(0.05, deadline - _time.monotonic()))
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                body = _read_response_bytes(
                    response,
                    VIDEO_POLL_RESPONSE_MAX_BYTES,
                    label="视频状态",
                ).decode("utf-8", errors="replace")
            transport_errors = 0
        except urllib.error.HTTPError as exc:
            # 404/405 usually means this poll path is wrong; try the next candidate quickly.
            if int(exc.code) in {404, 405}:
                return None
            transport_errors += 1
            if transport_errors >= 3:
                return None
            _time.sleep(2)
            continue
        except BusinessError:
            raise
        except Exception:
            transport_errors += 1
            if transport_errors >= 5:
                return None
            _time.sleep(2)
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        media_url = _extract_media_url(payload)
        if media_url:
            return payload
        status = str(payload.get("status") or payload.get("state") or "").lower()
        if status in {"failed", "error", "cancelled", "canceled", "expired"}:
            error_message = ""
            error = payload.get("error")
            if isinstance(error, dict):
                error_message = str(error.get("message") or error.get("code") or "").strip()
            elif isinstance(error, str):
                error_message = error.strip()
            if status == "expired":
                raise BusinessError(error_message or "视频生成任务已过期，请重新提交", code=50214, status_code=502)
            raise BusinessError(error_message or "视频生成任务失败", code=50214, status_code=502)
        if status in {"succeeded", "success", "completed", "complete", "done"} and not media_url:
            raise BusinessError("视频生成完成但未返回链接", code=50214, status_code=502)
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            break
        _time.sleep(min(2.0, max(0.2, remaining)))
    return None


def generate_video(
    config: GenerationModelConfig,
    prompt: str,
    input_image: str | list[str] | None = None,
    resolution: str = "",
    duration: str = "",
    aspect_ratio: str = "",
    user: str = "",
    on_job_created: Callable[[str, dict], None] | None = None,
) -> GeneratedImage:
    """Grok / xAI 兼容视频生成。优先解析返回 URL，支持原生存储。"""
    if not config.api_key.strip():
        raise BusinessError("模型供应商 API Key 为空", code=50201, status_code=502)
    deadline_monotonic = _request_deadline_monotonic(config.timeout_seconds)
    source_images = _input_images_from_values(
        input_image,
        effective_model_timeout_seconds(config.timeout_seconds),
        deadline_monotonic=deadline_monotonic,
    )
    endpoints = _video_endpoint_candidates(config.base_url)
    if not endpoints:
        raise BusinessError("视频模型 base_url 无效", code=50201, status_code=502)

    # If callers still pass duration via the old aspect_ratio slot, unpack it.
    if aspect_ratio and is_duration_code(aspect_ratio) and not duration:
        duration, aspect_ratio = aspect_ratio, "16:9"
    elif "|" in (duration or "") or "|" in (aspect_ratio or ""):
        packed = aspect_ratio if "|" in (aspect_ratio or "") else duration
        aspect_ratio, duration = unpack_video_task_aspect(packed)

    bodies = _video_request_bodies(
        config,
        prompt,
        resolution,
        duration,
        source_images,
        aspect_ratio=aspect_ratio,
        user=user,
    )
    headers = _authorization_headers(config)
    last_error: Exception | None = None

    for endpoint in endpoints:
        for body in bodies:
            try:
                payload = _post_json(endpoint, body, headers, _remaining_request_timeout(deadline_monotonic))
            except BusinessError as exc:
                last_error = exc
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = BusinessError(str(exc), code=50214, status_code=502)
                continue

            media_url = _resolve_video_media_url(
                _extract_media_url(payload) or "",
                create_endpoint=endpoint,
            )
            created_job_id = ""
            if not media_url and isinstance(payload, dict):
                job_id = payload.get("id") or payload.get("task_id") or payload.get("request_id")
                if job_id:
                    created_job_id = str(job_id).strip()
                    job_snapshot = {
                        "endpoint": _safe_provider_url(endpoint),
                        "body": _safe_request_value(body),
                        "poll_job_id": created_job_id,
                    }
                    logger.warning(
                        "video_job_created job_id=%s endpoint=%s",
                        created_job_id,
                        _safe_provider_url(endpoint),
                    )
                    if on_job_created is not None:
                        try:
                            on_job_created(created_job_id, job_snapshot)
                        except Exception:  # noqa: BLE001
                            logger.exception("video_job_created_callback_failed job_id=%s", created_job_id)
                    import time as _time
                    poll_candidates = _video_poll_url_candidates(endpoint, created_job_id)
                    # One shared task deadline covers creation, all poll URLs and download.
                    poll_deadline = deadline_monotonic
                    for poll_url in poll_candidates:
                        if _time.monotonic() >= poll_deadline:
                            break
                        try:
                            polled = _poll_video_job(
                                poll_url,
                                headers,
                                _remaining_request_timeout(deadline_monotonic),
                                deadline_monotonic=poll_deadline,
                            )
                        except BusinessError as exc:
                            last_error = exc
                            continue
                        if polled:
                            payload = polled
                            media_url = _resolve_video_media_url(
                                _extract_media_url(polled) or "",
                                poll_url=poll_url,
                                create_endpoint=endpoint,
                                prefer_task_content=uses_adobe_video_contract(
                                    config.vendor_model
                                ),
                            )
                            if media_url:
                                break
                    if not media_url:
                        continue

            if not media_url:
                last_error = BusinessError("视频接口未返回可识别的视频链接", code=50214, status_code=502)
                continue

            if media_url.startswith("data:"):
                image = _decode_base64_image(media_url, default_mime_type="video/mp4")
                result = GeneratedImage(
                    content=image.content,
                    mime_type=image.mime_type if str(image.mime_type).startswith("video/") else "video/mp4",
                    source_url=None,
                )
            else:
                try:
                    downloaded = _download_video(
                        _server_accessible_url(media_url),
                        _remaining_request_timeout(deadline_monotonic),
                        request_headers=headers,
                    )
                    result = GeneratedImage(
                        content=downloaded.content,
                        mime_type=downloaded.mime_type,
                        source_url=media_url,
                    )
                except BusinessError:
                    result = GeneratedImage(
                        content=b"",
                        mime_type=_guess_media_mime_from_url(media_url),
                        source_url=media_url,
                    )

            final_job_id = created_job_id
            if not final_job_id and isinstance(payload, dict):
                final_job_id = str(
                    payload.get("id") or payload.get("task_id") or payload.get("request_id") or ""
                ).strip()
            return _attach_provider_trace(
                result,
                {
                    "provider_request_id": final_job_id,
                    "provider_request_snapshot": {
                        "endpoint": _safe_provider_url(endpoint),
                        "body": _safe_request_value(body),
                        "poll_job_id": final_job_id or None,
                    },
                    "provider_response_summary": {
                        "video_url": media_url,
                        "provider_request_id": final_job_id or None,
                    },
                    "provider_http_status": 200,
                },
            )

    if last_error:
        raise last_error
    raise BusinessError("视频生成失败：上游未返回结果", code=50214, status_code=502)


def resume_video_job(
    config: GenerationModelConfig,
    job_id: str,
    *,
    create_endpoint: str = "",
    timeout: int | None = None,
) -> GeneratedImage:
    """Poll an existing upstream video job by id and return the finished media."""
    if not config.api_key.strip():
        raise BusinessError("模型供应商 API Key 为空", code=50201, status_code=502)
    job = str(job_id or "").strip()
    if not job:
        raise BusinessError("缺少上游视频任务 ID，无法续查", code=50214, status_code=502)

    if timeout is None:
        poll_timeout = float(effective_model_timeout_seconds(config.timeout_seconds))
    else:
        # A resume receives the *remaining* task budget. Do not reapply the
        # model minimum here, otherwise a final retry could gain extra time.
        poll_timeout = max(0.05, min(float(timeout), float(MAX_MODEL_TASK_TIMEOUT_SECONDS)))
    headers = _authorization_headers(config)

    endpoints: list[str] = []
    if create_endpoint:
        endpoints.append(create_endpoint)
    endpoints.extend(_video_endpoint_candidates(config.base_url))

    import time as _time

    last_error: Exception | None = None
    seen_poll: set[str] = set()
    poll_deadline = _time.monotonic() + poll_timeout
    for endpoint in endpoints:
        if _time.monotonic() >= poll_deadline:
            break
        for poll_url in _video_poll_url_candidates(endpoint, job):
            if poll_url in seen_poll:
                continue
            seen_poll.add(poll_url)
            if _time.monotonic() >= poll_deadline:
                break
            try:
                polled = _poll_video_job(
                    poll_url,
                    headers,
                    _remaining_request_timeout(poll_deadline),
                    deadline_monotonic=poll_deadline,
                )
            except BusinessError as exc:
                last_error = exc
                continue
            if not polled:
                continue
            media_url = _extract_media_url(polled)
            if not media_url:
                last_error = BusinessError("视频任务已结束但未返回链接", code=50214, status_code=502)
                continue
            media_url = _resolve_video_media_url(
                media_url,
                poll_url=poll_url,
                create_endpoint=endpoint,
                prefer_task_content=uses_adobe_video_contract(config.vendor_model),
            )
            if media_url.startswith("data:"):
                image = _decode_base64_image(media_url, default_mime_type="video/mp4")
                result = GeneratedImage(
                    content=image.content,
                    mime_type=image.mime_type if str(image.mime_type).startswith("video/") else "video/mp4",
                    source_url=None,
                )
            else:
                try:
                    downloaded = _download_video(
                        _server_accessible_url(media_url),
                        _remaining_request_timeout(poll_deadline),
                        request_headers=headers,
                    )
                    result = GeneratedImage(
                        content=downloaded.content,
                        mime_type=downloaded.mime_type,
                        source_url=media_url,
                    )
                except BusinessError:
                    result = GeneratedImage(
                        content=b"",
                        mime_type=_guess_media_mime_from_url(media_url),
                        source_url=media_url,
                    )
            return _attach_provider_trace(
                result,
                {
                    "provider_request_id": job,
                    "provider_request_snapshot": {
                        "endpoint": _safe_provider_url(endpoint),
                        "poll_job_id": job,
                        "poll_url": _safe_provider_url(poll_url),
                        "resumed": True,
                    },
                    "provider_response_summary": {"video_url": media_url, "provider_request_id": job},
                    "provider_http_status": 200,
                },
            )

    if last_error:
        raise last_error
    raise BusinessError("视频任务续查失败：上游未返回结果", code=50214, status_code=502)
