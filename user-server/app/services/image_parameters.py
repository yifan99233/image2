from __future__ import annotations

import re
from typing import Final

from app.core.exceptions import BusinessError


DEFAULT_IMAGE_QUALITY: Final = "auto"
SUPPORTED_IMAGE_QUALITIES: Final = frozenset({"auto", "low", "medium", "high"})


def normalize_image_quality(value: object) -> str:
    quality = str(value or DEFAULT_IMAGE_QUALITY).strip().lower()
    if quality not in SUPPORTED_IMAGE_QUALITIES:
        allowed = ", ".join(sorted(SUPPORTED_IMAGE_QUALITIES))
        raise BusinessError(
            f"quality 仅支持：{allowed}",
            code=40001,
            status_code=400,
        )
    return quality


SUPPORTED_IMAGE_FORMATS: Final = frozenset({"png", "jpeg", "webp"})


def normalize_image_size(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise BusinessError("size 必须是 auto 或宽x高像素", code=40001)
    size = value.strip().lower().replace("×", "x")
    if size == "auto":
        return size
    if not re.fullmatch(r"[0-9]{1,4}x[0-9]{1,4}", size):
        raise BusinessError("size 必须是 auto 或宽x高像素，例如 1536x1024", code=40001)
    width, height = map(int, size.split("x"))
    if not width or not height or width % 16 or height % 16:
        raise BusinessError("宽度和高度必须是 16 的正整数倍", code=40001)
    if max(width, height) > 3840 or max(width, height) > 3 * min(width, height):
        raise BusinessError("尺寸单边最多 3840 像素，宽高比需在 1:3 至 3:1 之间", code=40001)
    if not 655360 <= width * height <= 8294400:
        raise BusinessError("总像素需在 655360 至 8294400 之间", code=40001)
    return f"{width}x{height}"


def normalize_image_output_format(value: object) -> str | None:
    if value is None or value == "":
        return None
    output_format = str(value).strip().lower()
    if output_format == "jpg":
        output_format = "jpeg"
    if output_format not in SUPPORTED_IMAGE_FORMATS:
        raise BusinessError("图片格式仅支持 PNG、JPEG、WebP", code=40001)
    return output_format


def image_output_options(payload: dict) -> dict:
    # Omit unset fields to keep legacy batch idempotency hashes unchanged.
    size = normalize_image_size(payload.get("size"))
    output_format = normalize_image_output_format(payload.get("output_format"))
    return {**({"size": size} if size else {}),
            **({"output_format": output_format} if output_format else {})}
