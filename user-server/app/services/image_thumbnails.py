import hashlib
import hmac
import os
import tempfile
import urllib.request
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.services.asset_urls import canonicalize_asset_url
from app.services.site_scope import site_host_aliases

THUMBNAIL_EDGE_PX = 640
THUMBNAIL_QUALITY = 76
THUMBNAIL_MAX_PIXELS = 64_000_000
THUMBNAIL_CACHE_MAX_FILES = 5_000
THUMBNAIL_CACHE_TRIM_FILES = 500
THUMBNAIL_CACHE_DIR = Path(tempfile.gettempdir()) / "image2-thumbnails-v1"


def thumbnail_token(task_id: int, source_url: str) -> str:
    payload = f"{task_id}:{source_url}".encode("utf-8")
    return hmac.new(settings.jwt_secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()[:32]


def thumbnail_path(task_id: int, source_url: str, *, input_index: int | None = None) -> str:
    token = thumbnail_token(task_id, source_url)
    path = f"/image-tasks/{task_id}/thumbnail?token={token}"
    return f"{path}&input_index={input_index}" if input_index is not None else path


def is_valid_thumbnail_token(task_id: int, source_url: str, token: str) -> bool:
    return hmac.compare_digest(thumbnail_token(task_id, source_url), (token or "").strip())


def _source_download_url(source_url: str) -> str:
    public_root = canonicalize_asset_url(f"{settings.minio_public_endpoint.rstrip('/')}/{settings.minio_bucket}/")
    source = urlsplit(canonicalize_asset_url(source_url))
    public = urlsplit(public_root)
    if source.hostname in site_host_aliases(public_root) and source.path.startswith(public.path):
        storage_key = unquote(source.path[len(public.path) :])
        scheme = "https" if settings.minio_secure else "http"
        return f"{scheme}://{settings.minio_endpoint.rstrip('/')}/{settings.minio_bucket}/{quote(storage_key, safe='/')}"
    return source_url


def _read_source(source_url: str) -> bytes:
    request = urllib.request.Request(_source_download_url(source_url), method="GET")
    max_bytes = settings.image_result_download_max_bytes
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise BusinessError("原图过大，无法生成缩略图", code=40032, status_code=413)
                except ValueError:
                    pass
            content = response.read(max_bytes + 1)
    except BusinessError:
        raise
    except Exception as exc:
        raise BusinessError("缩略图原图读取失败", code=50221, status_code=502) from exc
    if not content or len(content) > max_bytes:
        raise BusinessError("原图过大或内容为空", code=40032, status_code=413)
    return content


def create_webp_thumbnail(content: bytes) -> bytes:
    try:
        with Image.open(BytesIO(content)) as source:
            if source.width * source.height > THUMBNAIL_MAX_PIXELS:
                raise BusinessError("原图像素过大，无法生成缩略图", code=40032, status_code=413)
            if source.format == "JPEG":
                source.draft("RGB", (THUMBNAIL_EDGE_PX, THUMBNAIL_EDGE_PX))
            normalized = ImageOps.exif_transpose(source)
            has_alpha = normalized.mode in {"RGBA", "LA"} or "transparency" in normalized.info
            image = normalized.convert("RGBA" if has_alpha else "RGB")
            image.thumbnail((THUMBNAIL_EDGE_PX, THUMBNAIL_EDGE_PX), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="WEBP", quality=THUMBNAIL_QUALITY, method=4, optimize=True)
            return output.getvalue()
    except BusinessError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise BusinessError("原图格式不支持缩略图", code=40033, status_code=415) from exc


def _cache_file(task_id: int, source_url: str) -> Path:
    return THUMBNAIL_CACHE_DIR / f"{task_id}-{thumbnail_token(task_id, source_url)}.webp"


def _trim_cache() -> None:
    files = list(THUMBNAIL_CACHE_DIR.glob("*.webp"))
    if len(files) <= THUMBNAIL_CACHE_MAX_FILES:
        return
    for path in sorted(files, key=lambda item: item.stat().st_mtime)[:THUMBNAIL_CACHE_TRIM_FILES]:
        path.unlink(missing_ok=True)


def get_or_create_thumbnail(task_id: int, source_url: str) -> bytes:
    cache_file = _cache_file(task_id, source_url)
    try:
        return cache_file.read_bytes()
    except FileNotFoundError:
        pass

    thumbnail = create_webp_thumbnail(_read_source(source_url))
    THUMBNAIL_CACHE_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{cache_file.name}.",
        suffix=".tmp",
        dir=THUMBNAIL_CACHE_DIR,
    )
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(thumbnail)
        os.replace(temporary_name, cache_file)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    _trim_cache()
    return thumbnail
