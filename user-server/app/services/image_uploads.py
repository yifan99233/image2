import base64
import asyncio
import hashlib
import hmac
import json
import logging
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from http.client import HTTPException
from pathlib import Path
from time import perf_counter
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import quote, urlparse

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.models.image_asset import ImageAsset
from app.models.user import User

logger = logging.getLogger(__name__)

QINIU_UPLOAD_MAX_ATTEMPTS = 3
QINIU_UPLOAD_RETRY_BASE_DELAY_SECONDS = 1.0
QINIU_UPLOAD_RETRYABLE_HTTP_STATUSES = frozenset({408, 429})
QINIU_OBJECT_EXISTS_STATUS = 614
_MINIO_BUCKET_READY: set[tuple[str, str, bool]] = set()
_MINIO_BUCKET_LOCK = threading.Lock()

MIME_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-m4v": ".m4v",
}

VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-m4v",
}

DETECTED_TYPE_TO_MIME = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
}


@dataclass(frozen=True)
class ImageMetadata:
    width: int | None
    height: int | None
    mime_type: str


@dataclass(frozen=True)
class StorageTarget:
    name: str
    provider: str
    bucket: str
    public_base_url: str
    key_prefix: str
    access_key: str = ""
    secret_key: str = ""
    upload_host: str = ""
    endpoint: str = ""
    secure: bool = False
    public_read: bool = True


def _r2_is_configured(*, require_public_url: bool = True) -> bool:
    required = (
        settings.r2_enabled,
        settings.r2_endpoint.strip(),
        settings.r2_access_key_id.strip(),
        settings.r2_secret_access_key.strip(),
        settings.r2_bucket.strip(),
    )
    if not all(required):
        return False
    return bool(settings.r2_public_base_url.strip()) if require_public_url else True


def _require_r2_configured(*, require_public_url: bool = True) -> None:
    if not _r2_is_configured(require_public_url=require_public_url):
        raise BusinessError("R2 图片存储配置未完成", code=50021, status_code=503)


def _r2_client():
    from minio import Minio

    raw_endpoint = settings.r2_endpoint.strip()
    parsed = urlparse(raw_endpoint if "://" in raw_endpoint else f"https://{raw_endpoint}")
    if not parsed.netloc:
        raise BusinessError("R2 端点配置无效", code=50021, status_code=503)
    return Minio(
        parsed.netloc,
        access_key=settings.r2_access_key_id,
        secret_key=settings.r2_secret_access_key,
        secure=parsed.scheme == "https",
    )


def _r2_public_url(object_key: str) -> str:
    _require_r2_configured()
    return f"{settings.r2_public_base_url.rstrip('/')}/{quote(object_key, safe='/')}"


def _r2_completion_signature(user_id: int, object_key: str, expires_at: int) -> str:
    payload = f"{int(user_id)}\n{object_key}\n{int(expires_at)}".encode("utf-8")
    return hmac.new(settings.jwt_secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _r2_completion_token(user_id: int, object_key: str, expires_at: int) -> str:
    return f"{int(expires_at)}.{_r2_completion_signature(user_id, object_key, expires_at)}"


def _verify_r2_completion_token(user_id: int, object_key: str, token: str) -> None:
    try:
        expires_raw, signature = (token or "").split(".", 1)
        expires_at = int(expires_raw)
    except (TypeError, ValueError):
        raise BusinessError("R2 上传确认凭证无效", code=40025, status_code=400) from None
    if expires_at < int(time.time()) or not hmac.compare_digest(
        signature,
        _r2_completion_signature(user_id, object_key, expires_at),
    ):
        raise BusinessError("R2 上传确认凭证已失效", code=40025, status_code=400)


def prepare_r2_upload(*, user_id: int, filename: str, mime_type: str, size_bytes: int) -> dict:
    """Create a browser-direct R2 PUT URL without exposing R2 credentials."""
    _require_r2_configured(require_public_url=True)
    if size_bytes <= 0 or size_bytes > settings.upload_max_bytes:
        raise BusinessError("图片不能超过 10MB", code=40021)
    allowed_mime_types = _allowed_mime_types()
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime not in allowed_mime_types:
        raise BusinessError("仅支持 JPG、PNG、WEBP 图片", code=40022)
    extension = MIME_TO_EXTENSION[normalized_mime]
    submitted_extension = Path(filename or "").suffix.lower()
    if submitted_extension and submitted_extension not in set(MIME_TO_EXTENSION.values()) | {".jpeg"}:
        raise BusinessError("图片扩展名不支持", code=40023)

    expires_at = int(time.time()) + settings.r2_upload_expires_seconds
    object_key = f"image2-staging/{int(user_id)}/{uuid.uuid4().hex}{extension}"
    try:
        upload_url = _r2_client().presigned_put_object(
            settings.r2_bucket,
            object_key,
            expires=timedelta(seconds=settings.r2_upload_expires_seconds),
        )
    except Exception as exc:
        logger.exception("r2 presigned upload creation failed bucket=%s key=%s", settings.r2_bucket, object_key)
        raise BusinessError("R2 上传服务暂不可用", code=50021, status_code=503) from exc
    return {
        "object_key": object_key,
        "upload_url": upload_url,
        "upload_method": "PUT",
        "content_type": normalized_mime,
        "r2_url": _r2_public_url(object_key),
        "expires_at": datetime.fromtimestamp(expires_at, UTC).isoformat(),
        "completion_token": _r2_completion_token(user_id, object_key, expires_at),
    }


def read_r2_uploaded_object(*, user_id: int, object_key: str, completion_token: str, submitted_mime_type: str) -> tuple[bytes, str]:
    _require_r2_configured(require_public_url=True)
    normalized_key = (object_key or "").strip()
    prefix = f"image2-staging/{int(user_id)}/"
    if not normalized_key.startswith(prefix) or "/" in normalized_key[len(prefix) :]:
        raise BusinessError("R2 上传对象无效", code=40025, status_code=400)
    _verify_r2_completion_token(user_id, normalized_key, completion_token)
    client = _r2_client()
    try:
        stat = client.stat_object(settings.r2_bucket, normalized_key)
        size_bytes = int(stat.size or 0)
        if size_bytes <= 0:
            raise BusinessError("R2 上传对象为空", code=40020, status_code=400)
        if size_bytes > settings.upload_max_bytes:
            raise BusinessError("图片不能超过 10MB", code=40021)
        response = client.get_object(settings.r2_bucket, normalized_key)
        try:
            content = response.read(settings.upload_max_bytes + 1)
        finally:
            response.close()
            response.release_conn()
    except BusinessError:
        raise
    except Exception as exc:
        logger.exception("r2 uploaded object read failed bucket=%s key=%s", settings.r2_bucket, normalized_key)
        raise BusinessError("R2 上传对象读取失败", code=50224, status_code=502) from exc
    if len(content) > settings.upload_max_bytes:
        raise BusinessError("图片不能超过 10MB", code=40021)
    content_type = (getattr(stat, "content_type", None) or submitted_mime_type or "").split(";", 1)[0].strip().lower()
    return content, content_type


def is_r2_hot_url_valid(r2_url: str | None, expires_at, *, now: datetime | None = None) -> bool:
    if not (r2_url or "").strip() or expires_at is None:
        return False
    current = now or datetime.now(UTC)
    expiry = expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry > current


def effective_asset_url(asset) -> str:
    if is_r2_hot_url_valid(getattr(asset, "r2_url", None), getattr(asset, "r2_expires_at", None)):
        return str(asset.r2_url)
    # `url` is the browser-facing URL. Qiniu-backed input assets also keep a
    # durable MinIO copy in `local_url` for upstream model downloads.
    return str(getattr(asset, "url", None) or getattr(asset, "local_url", None) or "")


def _allowed_mime_types() -> set[str]:
    return {mime.strip() for mime in settings.upload_allowed_mime_types.split(",") if mime.strip()}


def _allowed_generated_mime_types() -> set[str]:
    return _allowed_mime_types() | VIDEO_MIME_TYPES


def _is_video_mime(mime_type: str | None) -> bool:
    value = (mime_type or "").strip().lower()
    return value in VIDEO_MIME_TYPES or value.startswith("video/")


def _guess_media_mime_from_url(url: str, default: str = "video/mp4") -> str:
    lower = (url or "").split("?", 1)[0].split("#", 1)[0].lower()
    if lower.endswith(".webm"):
        return "video/webm"
    if lower.endswith(".mov"):
        return "video/quicktime"
    if lower.endswith(".m4v"):
        return "video/x-m4v"
    if lower.endswith((".mp4", ".mpeg4")):
        return "video/mp4"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    return default


def _detect_video_type(content: bytes) -> str | None:
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return "mp4"
    if len(content) >= 4 and content[0:4] == b"\x1aE\xdf\xa3":
        return "webm"
    return None


def _detect_png_dimensions(content: bytes) -> tuple[int, int] | None:
    if len(content) < 24 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    return struct.unpack(">II", content[16:24])


def _detect_jpeg_dimensions(content: bytes) -> tuple[int, int] | None:
    if len(content) < 4 or not content.startswith(b"\xff\xd8"):
        return None

    index = 2
    while index < len(content) - 9:
        if content[index] != 0xFF:
            index += 1
            continue
        marker = content[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(content):
            return None
        segment_length = struct.unpack(">H", content[index : index + 2])[0]
        if segment_length < 2:
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if index + 7 > len(content):
                return None
            height = struct.unpack(">H", content[index + 3 : index + 5])[0]
            width = struct.unpack(">H", content[index + 5 : index + 7])[0]
            return width, height
        index += segment_length
    return None


def _detect_webp_dimensions(content: bytes) -> tuple[int, int] | None:
    if len(content) < 30 or content[0:4] != b"RIFF" or content[8:12] != b"WEBP":
        return None

    chunk_type = content[12:16]
    if chunk_type == b"VP8X" and len(content) >= 30:
        width = 1 + int.from_bytes(content[24:27], "little")
        height = 1 + int.from_bytes(content[27:30], "little")
        return width, height
    if chunk_type == b"VP8 " and len(content) >= 30:
        width = struct.unpack("<H", content[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", content[28:30])[0] & 0x3FFF
        return width, height
    if chunk_type == b"VP8L" and len(content) >= 25:
        bits = int.from_bytes(content[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None


def _detect_image_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


def _extract_image_metadata(content: bytes, submitted_mime_type: str | None) -> ImageMetadata:
    detected_type = _detect_image_type(content) or _detect_video_type(content)
    detected_mime_type = DETECTED_TYPE_TO_MIME.get(detected_type or "")
    mime_type = detected_mime_type or submitted_mime_type or ""

    if mime_type == "image/png":
        dimensions = _detect_png_dimensions(content)
    elif mime_type == "image/jpeg":
        dimensions = _detect_jpeg_dimensions(content)
    elif mime_type == "image/webp":
        dimensions = _detect_webp_dimensions(content)
    else:
        dimensions = None

    return ImageMetadata(
        width=dimensions[0] if dimensions else None,
        height=dimensions[1] if dimensions else None,
        mime_type=mime_type,
    )


def _resolve_storage_provider(*, qiniu_storage_enabled: bool | None = None) -> str:
    """Prefer per-site admin UX toggle; fall back to env when toggle is unknown."""
    if qiniu_storage_enabled is True:
        return "qiniu"
    if qiniu_storage_enabled is False:
        return "minio"
    return settings.upload_storage_provider.strip().lower()


def _legacy_storage_target(*, qiniu_storage_enabled: bool | None = None) -> StorageTarget:
    provider = _resolve_storage_provider(qiniu_storage_enabled=qiniu_storage_enabled)
    if provider == "minio":
        return StorageTarget(
            name="legacy-minio",
            provider=provider,
            bucket=settings.minio_bucket,
            public_base_url=f"{settings.minio_public_endpoint.rstrip('/')}/{settings.minio_bucket}",
            key_prefix="",
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            endpoint=settings.minio_endpoint,
            secure=settings.minio_secure,
            public_read=settings.minio_public_read,
        )
    if provider == "qiniu":
        return StorageTarget(
            name="legacy-qiniu",
            provider=provider,
            bucket=settings.qiniu_bucket,
            public_base_url=settings.qiniu_cdn_base_url,
            key_prefix=settings.qiniu_image_prefix,
            access_key=settings.qiniu_access_key,
            secret_key=settings.qiniu_secret_key,
            upload_host=settings.qiniu_upload_host,
        )
    raise BusinessError("图片存储服务配置无效", code=50020, status_code=500)


def _active_storage_target(*, qiniu_storage_enabled: bool | None = None) -> StorageTarget:
    # An explicit site/model choice must override the named target. This keeps
    # material-library local uploads on MinIO even when the environment's
    # default target is a Qiniu CDN.
    if qiniu_storage_enabled is False:
        return _legacy_storage_target(qiniu_storage_enabled=False)
    raw_targets = settings.image_storage_targets_json.strip()
    if not raw_targets:
        return _legacy_storage_target(qiniu_storage_enabled=qiniu_storage_enabled)
    try:
        targets = json.loads(raw_targets)
    except json.JSONDecodeError as exc:
        raise BusinessError("图片存储目标配置不是有效 JSON", code=50020, status_code=500) from exc
    if not isinstance(targets, dict):
        raise BusinessError("图片存储目标配置必须是对象", code=50020, status_code=500)
    target_name = settings.image_storage_target.strip()
    target = targets.get(target_name)
    if not target_name or not isinstance(target, dict):
        raise BusinessError("未找到活动图片存储目标", code=50020, status_code=500)
    provider = str(target.get("provider") or "").strip().lower()
    public_base_url = str(target.get("public_base_url") or target.get("cdn_base_url") or "").strip()
    if provider not in {"minio", "qiniu"} or not public_base_url:
        raise BusinessError("图片存储目标配置无效", code=50020, status_code=500)
    return StorageTarget(
        name=target_name,
        provider=provider,
        bucket=str(target.get("bucket") or "").strip(),
        public_base_url=public_base_url,
        key_prefix=str(target.get("key_prefix") or "").strip().strip("/"),
        access_key=str(target.get("access_key") or "").strip(),
        secret_key=str(target.get("secret_key") or "").strip(),
        upload_host=str(target.get("upload_host") or "").strip(),
        endpoint=str(target.get("endpoint") or "").strip(),
        secure=bool(target.get("secure", False)),
        public_read=bool(target.get("public_read", True)),
    )


def _store_in_minio(*, target: StorageTarget, content: bytes, storage_key: str, mime_type: str) -> str:
    from minio import Minio
    from minio.error import S3Error

    started_at = perf_counter()
    client = Minio(
        target.endpoint,
        access_key=target.access_key,
        secret_key=target.secret_key,
        secure=target.secure,
    )
    bucket = target.bucket
    try:
        bucket_cache_key = (target.endpoint, bucket, bool(target.public_read))
        if bucket_cache_key not in _MINIO_BUCKET_READY:
            with _MINIO_BUCKET_LOCK:
                if bucket_cache_key not in _MINIO_BUCKET_READY:
                    if not client.bucket_exists(bucket):
                        client.make_bucket(bucket)
                    if target.public_read:
                        policy = {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Principal": {"AWS": ["*"]},
                                    "Action": ["s3:GetObject"],
                                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                                }
                            ],
                        }
                        client.set_bucket_policy(bucket, json.dumps(policy))
                    _MINIO_BUCKET_READY.add(bucket_cache_key)
        client.put_object(
            bucket,
            storage_key,
            BytesIO(content),
            length=len(content),
            content_type=mime_type,
        )
        logger.warning(
            "image_storage_timing stage=minio_store endpoint=%s bucket=%s key=%s elapsed=%.3fs bytes=%s mime_type=%s",
            target.endpoint,
            bucket,
            storage_key,
            perf_counter() - started_at,
            len(content),
            mime_type,
        )
    except Exception as exc:
        error_code = exc.code if isinstance(exc, S3Error) else type(exc).__name__
        logger.exception(
            "minio image storage failed: code=%s bucket=%s endpoint=%s key=%s elapsed=%.3fs",
            error_code,
            bucket,
            target.endpoint,
            storage_key,
            perf_counter() - started_at,
        )
        raise BusinessError("图片存储服务暂不可用", code=50020, status_code=500) from exc

    return f"{target.public_base_url.rstrip('/')}/{quote(storage_key, safe='/')}"


def _qiniu_urlsafe_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8")


def _qiniu_upload_token(target: StorageTarget, storage_key: str) -> str:
    if not all((target.access_key, target.secret_key, target.bucket, target.public_base_url, target.upload_host)):
        raise BusinessError("七牛云图片存储配置未完成", code=50020, status_code=500)

    policy = {
        "scope": f"{target.bucket}:{storage_key}",
        "deadline": int(time.time()) + 3600,
        "insertOnly": 1,
    }
    encoded_policy = _qiniu_urlsafe_base64(json.dumps(policy, separators=(",", ":")).encode("utf-8"))
    digest = hmac.new(target.secret_key.encode("utf-8"), encoded_policy.encode("utf-8"), hashlib.sha1).digest()
    return f"{target.access_key}:{_qiniu_urlsafe_base64(digest)}:{encoded_policy}"


def _encode_qiniu_multipart(*, token: str, storage_key: str, content: bytes, mime_type: str) -> tuple[bytes, str]:
    boundary = f"----image2-{uuid.uuid4().hex}"
    fields = (("token", token), ("key", storage_key))
    parts: list[bytes] = []
    for name, value in fields:
        parts.extend((
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
            value.encode("utf-8"),
            b"\r\n",
        ))
    parts.extend((
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="file"; filename="{Path(storage_key).name}"\r\n'.encode("utf-8"),
        f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _is_retryable_qiniu_upload_error(exc: BaseException) -> bool:
    if isinstance(exc, urlerror.HTTPError):
        return exc.code in QINIU_UPLOAD_RETRYABLE_HTTP_STATUSES or 500 <= exc.code < 600
    return isinstance(exc, (urlerror.URLError, TimeoutError, OSError))


def _qiniu_http_error_details(exc: BaseException) -> tuple[int | None, str, str]:
    if not isinstance(exc, urlerror.HTTPError):
        return None, "", ""
    request_id = exc.headers.get("X-Reqid", "") if exc.headers else ""
    try:
        response_body = (
            exc.read(512)
            .decode("utf-8", errors="replace")
            .replace("\r", " ")
            .replace("\n", " ")
            .strip()
        )
    except (OSError, ValueError):
        response_body = ""
    return exc.code, request_id, response_body


def _qiniu_content_etag(content: bytes) -> str:
    # Qiniu's published content hash: https://github.com/qiniu/qetag
    block_size = 4 * 1024 * 1024
    if len(content) <= block_size:
        digest = b"\x16" + hashlib.sha1(content).digest()
    else:
        blocks = b"".join(hashlib.sha1(content[i:i + block_size]).digest() for i in range(0, len(content), block_size))
        digest = b"\x96" + hashlib.sha1(blocks).digest()
    return _qiniu_urlsafe_base64(digest)


def _qiniu_object_matches(*, target: StorageTarget, storage_key: str, content: bytes) -> bool:
    """Resolve ambiguous upload outcomes only when the stored bytes match exactly."""
    url = f"{target.public_base_url.rstrip('/')}/{quote(storage_key, safe='/')}"
    started_at = perf_counter()
    try:
        request = urlrequest.Request(url, headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"})
        with urlrequest.urlopen(request, timeout=settings.qiniu_verify_timeout_seconds) as response:
            if response.status != 200:
                return False
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != len(content):
                return False
            etag = response.headers.get("ETag", "").strip().strip('"')
            if length is not None and etag == _qiniu_content_etag(content):
                return True
            digest = hashlib.sha256()
            received = 0
            while perf_counter() - started_at < settings.qiniu_verify_budget_seconds:
                chunk = response.read(min(65536, len(content) + 1 - received))
                if not chunk:
                    return received == len(content) and digest.digest() == hashlib.sha256(content).digest()
                received += len(chunk)
                if received > len(content):
                    return False
                digest.update(chunk)
    except (urlerror.URLError, OSError, ValueError, HTTPException) as exc:
        logger.warning("qiniu upload verification unavailable: key=%s error_type=%s", storage_key, type(exc).__name__)
    return False


def _store_in_qiniu(*, target: StorageTarget, content: bytes, storage_key: str, mime_type: str) -> str:
    started_at = perf_counter()
    token = _qiniu_upload_token(target, storage_key)
    body, content_type = _encode_qiniu_multipart(token=token, storage_key=storage_key, content=content, mime_type=mime_type)
    for attempt in range(1, QINIU_UPLOAD_MAX_ATTEMPTS + 1):
        request = urlrequest.Request(
            target.upload_host.rstrip("/"),
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        attempt_started_at = perf_counter()
        try:
            with urlrequest.urlopen(request, timeout=60) as response:
                if not 200 <= response.status < 300:
                    raise BusinessError("七牛云图片存储服务暂不可用", code=50020, status_code=500)
            logger.warning(
                "image_storage_timing stage=qiniu_store bucket=%s key=%s attempt=%s/%s elapsed=%.3fs "
                "attempt_elapsed=%.3fs bytes=%s mime_type=%s",
                target.bucket,
                storage_key,
                attempt,
                QINIU_UPLOAD_MAX_ATTEMPTS,
                perf_counter() - started_at,
                perf_counter() - attempt_started_at,
                len(content),
                mime_type,
            )
            return f"{target.public_base_url.rstrip('/')}/{quote(storage_key, safe='/')}"
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            retryable = _is_retryable_qiniu_upload_error(exc)
            status, request_id, response_body = _qiniu_http_error_details(exc)
            if (retryable or (status == QINIU_OBJECT_EXISTS_STATUS and attempt > 1)) and _qiniu_object_matches(
                target=target, storage_key=storage_key, content=content,
            ):
                # A timeout or 614 alone cannot prove that the complete object was stored.
                logger.warning(
                    "qiniu image storage verified after upload error: bucket=%s key=%s attempt=%s/%s "
                    "request_id=%s elapsed=%.3fs bytes=%s response=%s",
                    target.bucket,
                    storage_key,
                    attempt,
                    QINIU_UPLOAD_MAX_ATTEMPTS,
                    request_id or "-",
                    perf_counter() - started_at,
                    len(content),
                    response_body[:300] or "-",
                )
                return f"{target.public_base_url.rstrip('/')}/{quote(storage_key, safe='/')}"
            if retryable and attempt < QINIU_UPLOAD_MAX_ATTEMPTS:
                retry_delay = QINIU_UPLOAD_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "qiniu image storage retry: bucket=%s key=%s attempt=%s/%s retry_in=%.1fs "
                    "status=%s request_id=%s elapsed=%.3fs bytes=%s error=%s response=%s",
                    target.bucket,
                    storage_key,
                    attempt,
                    QINIU_UPLOAD_MAX_ATTEMPTS,
                    retry_delay,
                    status if status is not None else "-",
                    request_id or "-",
                    perf_counter() - attempt_started_at,
                    len(content),
                    str(exc)[:300],
                    response_body[:300] or "-",
                )
                time.sleep(retry_delay)
                continue

            logger.exception(
                "qiniu image storage failed: bucket=%s key=%s attempt=%s/%s retryable=%s status=%s "
                "request_id=%s elapsed=%.3fs bytes=%s error=%s response=%s",
                target.bucket,
                storage_key,
                attempt,
                QINIU_UPLOAD_MAX_ATTEMPTS,
                retryable,
                status if status is not None else "-",
                request_id or "-",
                perf_counter() - started_at,
                len(content),
                str(exc)[:300],
                response_body[:300] or "-",
            )
            raise BusinessError("七牛云图片存储服务暂不可用", code=50020, status_code=500) from exc

    raise BusinessError("七牛云图片存储服务暂不可用", code=50020, status_code=500)


def _store_image(
    *,
    content: bytes,
    storage_key: str,
    mime_type: str,
    qiniu_storage_enabled: bool | None = None,
) -> str:
    target = _active_storage_target(qiniu_storage_enabled=qiniu_storage_enabled)
    if target.provider == "minio":
        return _store_in_minio(target=target, content=content, storage_key=storage_key, mime_type=mime_type)
    if target.provider == "qiniu":
        return _store_in_qiniu(target=target, content=content, storage_key=storage_key, mime_type=mime_type)
    raise BusinessError("图片存储服务配置无效", code=50020, status_code=500)


def _store_local_image(*, content: bytes, storage_key: str, mime_type: str) -> str:
    """Always write the durable backup to the server-side MinIO bucket.

    This deliberately bypasses the site-level Qiniu toggle. An R2 hot object
    needs a domestic/server-side fallback even when the site is configured to
    use a third-party CDN for ordinary assets.
    """
    target = _legacy_storage_target(qiniu_storage_enabled=False)
    return _store_in_minio(target=target, content=content, storage_key=storage_key, mime_type=mime_type)


def _image_storage_key(
    relative_dir: Path,
    filename: str,
    *,
    qiniu_storage_enabled: bool | None = None,
) -> str:
    relative_key = str(relative_dir / filename)
    prefix = _active_storage_target(qiniu_storage_enabled=qiniu_storage_enabled).key_prefix
    return f"{prefix}/{relative_key}" if prefix else relative_key


def _local_storage_key(relative_dir: Path, filename: str) -> str:
    return str(relative_dir / filename)


def _validate_uploaded_content(*, content: bytes, original_filename: str, submitted_mime_type: str) -> ImageMetadata:
    if not content:
        raise BusinessError("请选择要上传的图片", code=40020)
    if len(content) > settings.upload_max_bytes:
        raise BusinessError("图片不能超过 10MB", code=40021)

    metadata = _extract_image_metadata(content, submitted_mime_type)
    if metadata.mime_type not in _allowed_mime_types():
        raise BusinessError("仅支持 JPG、PNG、WEBP 图片", code=40022)

    if original_filename:
        submitted_extension = Path(original_filename).suffix.lower()
        if submitted_extension and submitted_extension not in set(MIME_TO_EXTENSION.values()) | {".jpeg"}:
            raise BusinessError("图片扩展名不支持", code=40023)
    return metadata


async def _save_uploaded_content(
    *,
    db: AsyncSession,
    current_user: User,
    content: bytes,
    original_filename: str,
    submitted_mime_type: str,
    hot_url: str | None = None,
    local_backup_only: bool = False,
    qiniu_storage_enabled: bool | None = None,
) -> ImageAsset:
    from app.api.routes.ux import get_qiniu_storage_enabled

    metadata = _validate_uploaded_content(
        content=content,
        original_filename=original_filename,
        submitted_mime_type=submitted_mime_type,
    )
    extension = MIME_TO_EXTENSION[metadata.mime_type]
    digest = hashlib.sha256(content).hexdigest()
    relative_dir = Path("images") / str(current_user.id)
    filename = f"{uuid.uuid4().hex}{extension}"
    if local_backup_only:
        storage_key = _local_storage_key(relative_dir, filename)
        url = await asyncio.to_thread(
            _store_local_image,
            content=content,
            storage_key=storage_key,
            mime_type=metadata.mime_type,
        )
        local_url = url
    else:
        if qiniu_storage_enabled is None:
            qiniu_storage_enabled = await get_qiniu_storage_enabled(db, current_user.site_id)
        storage_target = _active_storage_target(qiniu_storage_enabled=qiniu_storage_enabled)
        storage_key = _image_storage_key(relative_dir, filename, qiniu_storage_enabled=qiniu_storage_enabled)
        if storage_target.provider == "qiniu":
            # Keep the CDN URL for browser delivery, but always retain a
            # server-side copy for model workers whose route to the CDN can
            # time out or fail TLS handshakes.
            url = await asyncio.to_thread(
                _store_in_qiniu,
                target=storage_target,
                content=content,
                storage_key=storage_key,
                mime_type=metadata.mime_type,
            )
            local_storage_key = _local_storage_key(relative_dir, filename)
            local_url = await asyncio.to_thread(
                _store_local_image,
                content=content,
                storage_key=local_storage_key,
                mime_type=metadata.mime_type,
            )
            logger.warning(
                "image_storage_timing stage=dual_store_upload qiniu_url=%s local_url=%s bytes=%s",
                url,
                local_url,
                len(content),
            )
        else:
            url = await asyncio.to_thread(
                _store_image,
                content=content,
                storage_key=storage_key,
                mime_type=metadata.mime_type,
                qiniu_storage_enabled=qiniu_storage_enabled,
            )
            local_url = url
    normalized_hot_url = (hot_url or "").strip() or None
    r2_expires_at = (
        datetime.now(UTC) + timedelta(seconds=settings.r2_hot_url_ttl_seconds)
        if normalized_hot_url
        else None
    )
    asset = ImageAsset(
        site_id=current_user.site_id,
        user_id=current_user.id,
        storage_key=storage_key,
        url=url,
        local_url=local_url,
        r2_url=normalized_hot_url,
        r2_expires_at=r2_expires_at,
        mime_type=metadata.mime_type,
        width=metadata.width,
        height=metadata.height,
        size_bytes=len(content),
        sha256=digest,
        source="upload",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def save_uploaded_image(
    *,
    db: AsyncSession,
    current_user: User,
    upload: UploadFile,
    qiniu_storage_enabled: bool | None = None,
) -> ImageAsset:
    content = await upload.read()
    return await _save_uploaded_content(
        db=db,
        current_user=current_user,
        content=content,
        original_filename=upload.filename or "",
        submitted_mime_type=upload.content_type or "",
        qiniu_storage_enabled=qiniu_storage_enabled,
    )


async def save_uploaded_r2_image(
    *,
    db: AsyncSession,
    current_user: User,
    object_key: str,
    completion_token: str,
    submitted_mime_type: str,
) -> ImageAsset:
    content, content_type = await asyncio.to_thread(
        read_r2_uploaded_object,
        user_id=int(current_user.id),
        object_key=object_key,
        completion_token=completion_token,
        submitted_mime_type=submitted_mime_type,
    )
    return await _save_uploaded_content(
        db=db,
        current_user=current_user,
        content=content,
        original_filename=Path(object_key).name,
        submitted_mime_type=content_type or submitted_mime_type,
        hot_url=_r2_public_url(object_key),
        local_backup_only=True,
    )


async def save_generated_image(
    *,
    db: AsyncSession,
    user_id: int,
    site_id: int,
    content: bytes,
    mime_type: str,
) -> ImageAsset:
    from app.api.routes.ux import get_qiniu_storage_enabled

    allowed_mime_types = _allowed_mime_types()
    metadata = _extract_image_metadata(content, mime_type)
    if not content:
        raise BusinessError("模型未返回图片内容", code=50030, status_code=500)
    if metadata.mime_type not in allowed_mime_types:
        raise BusinessError("模型返回的图片格式不受支持", code=50031, status_code=500)

    qiniu_storage_enabled = await get_qiniu_storage_enabled(db, site_id)
    extension = MIME_TO_EXTENSION[metadata.mime_type]
    digest = hashlib.sha256(content).hexdigest()
    relative_dir = Path("generated") / str(user_id)
    filename = f"{uuid.uuid4().hex}{extension}"
    storage_key = _image_storage_key(relative_dir, filename, qiniu_storage_enabled=qiniu_storage_enabled)
    url = _store_image(
        content=content,
        storage_key=storage_key,
        mime_type=metadata.mime_type,
        qiniu_storage_enabled=qiniu_storage_enabled,
    )

    asset = ImageAsset(
        site_id=site_id,
        user_id=user_id,
        storage_key=storage_key,
        url=url,
        local_url=url,
        mime_type=metadata.mime_type,
        width=metadata.width,
        height=metadata.height,
        size_bytes=len(content),
        sha256=digest,
        source="generated",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


def store_generated_image_object(
    *,
    user_id: int,
    content: bytes,
    mime_type: str,
    qiniu_storage_enabled: bool | None = None,
    hot_url: str | None = None,
) -> dict:
    if not content:
        raise BusinessError("模型未返回媒体内容", code=50030, status_code=500)

    allowed_mime_types = _allowed_generated_mime_types()
    metadata = _extract_image_metadata(content, mime_type)
    resolved_mime = metadata.mime_type if metadata.mime_type in allowed_mime_types else (mime_type or "").strip().lower()
    if _is_video_mime(resolved_mime) and resolved_mime not in VIDEO_MIME_TYPES:
        # Normalize uncommon video/* to mp4 for extension mapping.
        resolved_mime = "video/mp4"
    if resolved_mime not in allowed_mime_types and not _is_video_mime(resolved_mime):
        raise BusinessError("模型返回的媒体格式不受支持", code=50031, status_code=500)
    if resolved_mime not in MIME_TO_EXTENSION and _is_video_mime(resolved_mime):
        resolved_mime = "video/mp4"

    extension = MIME_TO_EXTENSION.get(resolved_mime)
    if not extension:
        raise BusinessError("模型返回的媒体格式不受支持", code=50031, status_code=500)

    digest = hashlib.sha256(content).hexdigest()
    relative_dir = Path("generated") / str(user_id)
    filename = f"{uuid.uuid4().hex}{extension}"
    normalized_hot_url = (hot_url or "").strip() or None
    if normalized_hot_url:
        # The upstream has already written the R2 object. Only create the
        # durable server-side copy here; do not write the result to R2 again.
        storage_key = _local_storage_key(relative_dir, filename)
        local_url = _store_local_image(content=content, storage_key=storage_key, mime_type=resolved_mime)
        r2_expires_at = datetime.now(UTC) + timedelta(seconds=settings.r2_hot_url_ttl_seconds)
    else:
        storage_key = _image_storage_key(relative_dir, filename, qiniu_storage_enabled=qiniu_storage_enabled)
        local_url = _store_image(
            content=content,
            storage_key=storage_key,
            mime_type=resolved_mime,
            qiniu_storage_enabled=qiniu_storage_enabled,
        )
        r2_expires_at = None
    return {
        "storage_key": storage_key,
        "url": local_url,
        "local_url": local_url,
        "r2_url": normalized_hot_url,
        "r2_expires_at": r2_expires_at,
        "mime_type": resolved_mime,
        "width": metadata.width,
        "height": metadata.height,
        "size_bytes": len(content),
        "sha256": digest,
    }


def store_native_generated_object(
    *,
    user_id: int,
    source_url: str,
    mime_type: str | None = None,
) -> dict:
    """Keep provider-hosted media URL without re-uploading bytes (Grok/xAI native links)."""
    url = (source_url or "").strip()
    if not url:
        raise BusinessError("原生存储缺少媒体链接", code=50032, status_code=500)

    resolved_mime = (mime_type or "").strip().lower()
    if not resolved_mime or resolved_mime == "application/octet-stream":
        resolved_mime = _guess_media_mime_from_url(url)
    if _is_video_mime(resolved_mime) and resolved_mime not in VIDEO_MIME_TYPES:
        resolved_mime = "video/mp4"
    if not resolved_mime:
        resolved_mime = "video/mp4"

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    extension = MIME_TO_EXTENSION.get(resolved_mime, ".bin")
    storage_key = f"native/{user_id}/{digest}{extension}"
    return {
        "storage_key": storage_key,
        "url": url,
        "local_url": None,
        "r2_url": None,
        "r2_expires_at": None,
        "mime_type": resolved_mime,
        "width": None,
        "height": None,
        "size_bytes": 0,
        "sha256": digest,
    }


async def create_generated_image_asset(
    *,
    db: AsyncSession,
    user_id: int,
    site_id: int,
    stored_image: dict,
) -> ImageAsset:
    asset = ImageAsset(
        site_id=site_id,
        user_id=user_id,
        storage_key=stored_image["storage_key"],
        url=stored_image["url"],
        local_url=(stored_image["local_url"] if "local_url" in stored_image else stored_image["url"]),
        r2_url=stored_image.get("r2_url"),
        r2_expires_at=stored_image.get("r2_expires_at"),
        mime_type=stored_image["mime_type"],
        width=stored_image["width"],
        height=stored_image["height"],
        size_bytes=stored_image["size_bytes"],
        sha256=stored_image["sha256"],
        source="generated",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset
