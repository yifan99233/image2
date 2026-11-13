"""Duration policy shared by video admission and upstream serialization."""
import re

from app.core.exceptions import BusinessError

# Muse assembles longer videos from segments. Other contracts retain their limit.
VIDEO_DURATION_LIMITS = {"muse": 60, "default": 15}


def normalize_video_duration_seconds(value: str, vendor_model: str = "") -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    match = re.fullmatch(r"([0-9]+)\s*s?", text)
    maximum = VIDEO_DURATION_LIMITS["muse" if vendor_model.strip().lower().startswith("muse-") else "default"]
    if match is None or not 1 <= int(match[1]) <= maximum:
        raise BusinessError(f"视频时长需在 1–{maximum} 秒之间", code=40001, status_code=400)
    return int(match[1])
