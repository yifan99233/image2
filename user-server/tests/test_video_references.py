from io import BytesIO
from types import SimpleNamespace
import wave

import pytest
from fastapi import UploadFile
from PIL import Image

from app.api.routes import catalog, uploads
from app.api.routes.catalog_serializers import guess_asset_mime_type
from app.core.exceptions import BusinessError
from app.services import image_generation, image_uploads
from app.services.video_references import inspect_reference, validate_video_references, video_reference_capabilities


def media_bytes(kind):
    stream = BytesIO()
    if kind == "image":
        Image.new("RGB", (16, 16), "blue").save(stream, "PNG")
    elif kind == "audio":
        with wave.open(stream, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\0\0" * 80)
    else:
        # ISO BMFF signature and video handler; transport tests use a tiny body.
        stream.write(b"\0\0\0\x18ftypisom\0\0\0\0isommp42\0\0\0\x18hdlr\0\0\0\0\0\0\0\0vide")
    return stream.getvalue()


@pytest.mark.parametrize("model,kinds", [
    ("firefly-veo31-lite", ["image"]),
    ("firefly-omniflash", ["image", "video"]),
    ("muse-video", ["image", "video", "audio"]),
    ("muse-video-cdn", ["image", "video", "audio"]),
])
def test_capabilities_and_actual_bytes(model, kinds):
    caps = video_reference_capabilities(model)
    assert caps["kinds"] == kinds
    refs = [(inspect_reference(media_bytes(kind))[0], len(media_bytes(kind))) for kind in kinds]
    validate_video_references(refs, caps)


@pytest.mark.parametrize("model,refs,message", [
    ("firefly-veo31-lite", [("video/mp4", 30)], "不支持"),
    ("firefly-omniflash", [("audio/wav", 30)], "不支持"),
    ("firefly-veo31-lite", [("image/webp", 30)], "不支持"),
    ("firefly-omniflash", [("video/mp4", 30)] * 4, "最多支持 3"),
    ("muse-video", [("image/png", 30)] * 5, "最多支持 4"),
    ("muse-video", [("video/mp4", 13 << 20), ("audio/wav", 12 << 20)], "合计"),
    ("firefly-seed25", [("audio/wav", 16 << 20)], "不能超过 15MB"),
    ("firefly-seed20", [("audio/wav", 30)], "同时添加"),
])
def test_rejects_unsupported_or_excessive_references(model, refs, message):
    with pytest.raises(BusinessError, match=message):
        validate_video_references(refs, video_reference_capabilities(model))


def test_audio_can_upload_before_visual_companion_and_html_is_rejected():
    validate_video_references([("audio/wav", 100)], video_reference_capabilities("firefly-seed20"), complete=False)
    with pytest.raises(BusinessError, match="格式不支持"):
        inspect_reference(b"<html>not a video</html>")


class Rows:
    def __init__(self, rows): self.rows = rows
    def __iter__(self): return iter(self.rows)
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None


class OwnedAssets:
    def __init__(self, assets): self.assets = assets
    async def execute(self, statement):
        params = statement.compile().params
        assert params["site_id_1"] == 7
        assert params["user_id_1"] == 9
        return Rows(self.assets)


@pytest.mark.parametrize("by_id", [True, False])
async def test_admission_checks_owned_media_preserves_order_and_image_tasks_reject_audio(by_id):
    assets = [SimpleNamespace(id=1, url="https://cdn.test/a.wav", local_url=None, r2_url=None, mime_type="audio/wav", size_bytes=100),
              SimpleNamespace(id=2, url="https://cdn.test/b.png", local_url=None, r2_url=None, mime_type="image/png", size_bytes=100)]
    payload = {"input_image_ids": [2, 1]} if by_id else {"input_image_urls": [assets[1].url, assets[0].url]}
    kwargs = dict(db=OwnedAssets(assets), site_id=7, user_id=9, payload=payload, max_input_images=4)
    assert await catalog.resolve_input_image_urls(**kwargs, video_capabilities=video_reference_capabilities("muse-video")) == [assets[1].url, assets[0].url]
    with pytest.raises(BusinessError, match="图片任务仅支持图片"):
        await catalog.resolve_input_image_urls(**kwargs)
    with pytest.raises(BusinessError, match="不支持"):
        await catalog.resolve_input_image_urls(**kwargs, video_capabilities=video_reference_capabilities("firefly-omniflash"))
    with pytest.raises(BusinessError) as failure:
        await catalog.resolve_input_image_urls(**{**kwargs, "db": OwnedAssets([])}, video_capabilities=video_reference_capabilities("muse-video"))
    assert failure.value.code == 40420


async def test_upload_checks_bytes_uses_model_storage_and_returns_audio(monkeypatch):
    saved = []
    class DB:
        async def execute(self, statement):
            params = statement.compile().params
            assert params["site_id_1"] == 7 and params["id_1"] == 3
            return Rows([SimpleNamespace(work_type="text_to_video,image_to_video", vendor_model="muse-video", max_input_images=1, storage_mode="local")])
        def add(self, asset): saved.append(asset)
        async def commit(self): pass
        async def refresh(self, asset): asset.id = 33
    def store(**kwargs):
        assert kwargs["mime_type"] == "audio/wav" and kwargs["content"] == media_bytes("audio")
        return "https://cdn.test/" + kwargs["storage_key"]
    monkeypatch.setattr("app.services.model_cdn.for_model", lambda *_: None)
    monkeypatch.setattr(image_uploads, "_store_image", store)
    upload = UploadFile(filename="misleading.png", file=BytesIO(media_bytes("audio")))
    response = await uploads.upload_video_reference(file=upload, model_id=3, db=DB(), current_user=SimpleNamespace(site_id=7, id=9))
    assert response.data.id == 33 and response.data.mime_type == "audio/wav"
    assert response.data.url.endswith(".wav") and response.data.width is None
    assert saved[0].site_id == 7 and saved[0].user_id == 9
    assert guess_asset_mime_type(response.data.url) == "audio/wav"


async def test_bounded_upload_rejects_oversize_before_storage():
    class Upload:
        async def read(self, size):
            assert size == 24 * 1024 * 1024 + 1
            return b"x" * size
    with pytest.raises(BusinessError, match="不能超过 24MB"):
        await image_uploads.save_uploaded_video_reference(db=None, current_user=None, upload=Upload(), capabilities=video_reference_capabilities("muse-video"))


@pytest.mark.parametrize("model,kinds", [("firefly-veo31-lite", ["image", "image"]), ("firefly-omniflash", ["image", "video"]), ("muse-video", ["image", "video", "audio"])])
def test_worker_forwards_typed_refs_once_and_polls_same_job(monkeypatch, model, kinds):
    inputs = {f"https://cdn.test/{i}": media_bytes(kind) for i, kind in enumerate(kinds)}
    monkeypatch.setattr(image_generation, "_download_image", lambda url, *a, **kw: image_generation.GeneratedImage(inputs[url], "application/octet-stream", source_url=url))
    posted, polled, saved = [], [], []
    def post(url, body, *_):
        posted.append((url, body))
        return {"id": "video-123", "status": "queued"}
    def poll(url, *_, **_kw):
        polled.append(url)
        return {"id": "video-123", "status": "completed", "url": "https://cdn.test/result.mp4"}
    monkeypatch.setattr(image_generation, "_post_json", post)
    monkeypatch.setattr(image_generation, "_poll_video_job", poll)
    monkeypatch.setattr(image_generation, "_download_video", lambda url, *_args, **_kw: image_generation.GeneratedImage(b"result", "video/mp4", source_url=url))
    config = image_generation.GenerationModelConfig("gateway", "Gateway", "https://gateway.test/v1", "api", "fixture-key", "bearer", 120, model)
    result = image_generation.generate_video(config, "animate", list(inputs), "720p", "4", "16:9", on_job_created=lambda job, snapshot: saved.append(job))
    assert result.mime_type == "video/mp4" and saved == ["video-123"]
    assert len(posted) == 1 and posted[0][0] == "https://gateway.test/v1/videos"
    assert posted[0][1]["reference_media"] == [{"url": url, "kind": kind} for url, kind in zip(inputs, kinds)]
    assert all("video-123" in url for url in polled) and polled
    assert "image" not in posted[0][1] and "images" not in posted[0][1]


@pytest.mark.parametrize("model", ["muse-video", "firefly-omniflash"])
def test_ambiguous_submit_never_probes_another_body_or_endpoint(monkeypatch, model):
    calls = []
    def post(url, *_):
        calls.append(url)
        raise BusinessError("upstream timeout", code=408, status_code=408)
    monkeypatch.setattr(image_generation, "_post_json", post)
    config = image_generation.GenerationModelConfig("gateway", "Gateway", "https://gateway.test/v1", "api", "fixture-key", "bearer", 120, model)
    with pytest.raises(BusinessError):
        image_generation.generate_video(config, "animate", resolution="720p", duration="4")
    assert calls == ["https://gateway.test/v1/videos"]


async def test_catalog_video_union_is_not_a_billable_work_type():
    assert catalog.requested_work_types("video") == ["text_to_video", "image_to_video"]
    with pytest.raises(BusinessError, match="视频任务类型"):
        await catalog.quote(1, {"work_type": "video"}, None, None)
