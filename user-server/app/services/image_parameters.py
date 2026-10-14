from __future__ import annotations

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
