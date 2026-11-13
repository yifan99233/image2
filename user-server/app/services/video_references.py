"""Video reference capabilities shared by upload, admission and serialization."""
from collections import Counter
from io import BytesIO

from PIL import Image

from app.core.exceptions import BusinessError

MIB = 1024 * 1024
IMAGE_MIMES = ["image/png", "image/jpeg"]
VIDEO_MIMES = ["video/mp4", "video/webm", "video/quicktime"]
AUDIO_MIMES = ["audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg"]


def video_reference_capabilities(vendor_model: str, max_images: int = 1) -> dict:
    model = str(vendor_model or "").strip().lower()
    limits = {"image": max(0, max_images)}
    sizes = {"image": 10 * MIB}
    mimes = IMAGE_MIMES + ["image/webp"]
    total_bytes = None
    contract = "image"
    frame_order = False
    requires_visual = False
    if model.startswith("muse-"):
        limits = {"image": 4, "video": 4, "audio": 4}
        sizes = dict.fromkeys(limits, 24 * MIB)
        mimes += ["image/gif"] + VIDEO_MIMES + AUDIO_MIMES
        max_total, total_bytes, contract = 4, 24 * MIB, "muse"
    elif model in {"firefly-veo31-lite", "firefly-omniflash", "firefly-omniflash11", "firefly-seed20", "firefly-seed25"}:
        contract = "firefly"
        mimes = list(IMAGE_MIMES)
        if model.endswith("veo31-lite"):
            limits, max_total, frame_order = {"image": 2}, 2, True
        elif "omniflash" in model:
            limits, max_total = {"image": 10, "video": 3}, 10
        else:
            large = model.endswith("seed25")
            limits = {"image": 30 if large else 9, "video": 10 if large else 3, "audio": 10 if large else 3}
            max_total, requires_visual = (50 if large else 12), True
        sizes = dict.fromkeys(limits, 50 * MIB)
        if "seed" in model:
            sizes["image"] = 30 * MIB
        if model.endswith("seed25"):
            sizes["audio"] = 15 * MIB
        if "video" in limits:
            mimes += VIDEO_MIMES
        if "audio" in limits:
            mimes += AUDIO_MIMES
    else:
        max_total = max(0, max_images)
    return {
        "kinds": list(limits), "mime_types": mimes, "max_total": max_total,
        "max_by_kind": limits, "max_bytes_by_kind": sizes, "max_total_bytes": total_bytes,
        "frame_order": frame_order, "audio_requires_visual": requires_visual, "contract": contract,
    }


def validate_video_references(refs: list[tuple[str, int]], caps: dict, *, complete: bool = True) -> None:
    if len(refs) > caps["max_total"]:
        raise BusinessError(f"当前模型最多支持 {caps['max_total']} 个参考素材", code=40001)
    counts = Counter()
    total_bytes = 0
    for mime, size in refs:
        kind = mime.split("/")[0]
        if mime not in caps["mime_types"] or kind not in caps["kinds"]:
            raise BusinessError(f"当前模型不支持 {mime} 参考素材，请移除或更换模型", code=40022)
        counts[kind] += 1
        if counts[kind] > caps["max_by_kind"][kind]:
            label = {"image": "图片", "video": "视频", "audio": "音频"}[kind]
            raise BusinessError(f"当前模型最多支持 {caps['max_by_kind'][kind]} 个{label}素材", code=40001)
        if size > caps["max_bytes_by_kind"][kind]:
            raise BusinessError(f"单个素材不能超过 {caps['max_bytes_by_kind'][kind] // MIB}MB", code=40021)
        total_bytes += size
    if caps["max_total_bytes"] and total_bytes > caps["max_total_bytes"]:
        raise BusinessError(f"参考素材合计不能超过 {caps['max_total_bytes'] // MIB}MB", code=40021)
    if complete and caps["audio_requires_visual"] and counts["audio"] and not (counts["image"] or counts["video"]):
        raise BusinessError("音频参考需要同时添加图片或视频素材", code=40001)


def inspect_reference(content: bytes) -> tuple[str, int | None, int | None]:
    """Identify bytes, never trust the browser's extension or Content-Type."""
    if content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")) or content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        try:
            with Image.open(BytesIO(content)) as image:
                mime, width, height = Image.MIME[image.format], *image.size
                image.verify()
            return mime, width, height
        except Exception as exc:
            raise BusinessError("图片文件损坏或格式不支持", code=40022) from exc
    if len(content) >= 12:
        if content[:4] == b"RIFF" and content[8:12] == b"WAVE":
            return "audio/wav", None, None
        if content.startswith(b"OggS") and (b"OpusHead" in content[:4096] or b"vorbis" in content[:4096]):
            return "audio/ogg", None, None
        if content[4:8] == b"ftyp":
            brand = content[8:12]
            # M4A brands identify audio; generic MP4 containers must expose a
            # video handler. Do not classify an audio-only MP4 as video.
            if brand in {b"M4A ", b"M4B "} or b"soun" in content and b"vide" not in content:
                return "audio/mp4", None, None
            if b"vide" in content:
                return ("video/quicktime" if brand == b"qt  " else "video/mp4"), None, None
        if content.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in content[:4096]:
            return "video/webm", None, None
        if content.startswith(b"ID3") or content[0] == 0xFF and content[1] & 0xE0 == 0xE0:
            return "audio/mpeg", None, None
    raise BusinessError("素材格式不支持，请使用模型支持的图片、视频或音频格式", code=40022)
