import base64
import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image

from app.api.routes import catalog_exports
from app.services import image_generation, image_uploads


@pytest.fixture
def animated_gif():
    output = BytesIO()
    first = Image.new("RGB", (12, 8), "red")
    second = Image.new("RGB", (12, 8), "blue")
    first.save(output, format="GIF", save_all=True, append_images=[second],
               duration=[100, 200], loop=0)
    return output.getvalue()


@pytest.mark.parametrize("mime", ["image/gif", "image/png", "application/octet-stream"])
@pytest.mark.parametrize("storage", ["local", "cdn", "hot_url"])
def test_generated_gif_keeps_animation_and_actual_mime(monkeypatch, animated_gif, mime, storage):
    saved = {}

    def store(**kwargs):
        saved.update(kwargs)
        return "https://storage.example/" + kwargs["storage_key"]

    monkeypatch.setattr(image_uploads, "_store_image", store)
    monkeypatch.setattr(image_uploads, "_store_local_image", store)
    monkeypatch.setattr(image_uploads.settings, "upload_allowed_mime_types", "image/png,image/jpeg,image/webp")
    result = image_uploads.store_generated_image_object(
        user_id=7, content=animated_gif, mime_type=mime,
        qiniu_storage_enabled=storage == "cdn",
        hot_url="https://hot.example/result.gif" if storage == "hot_url" else None,
    )
    assert saved["content"] == animated_gif
    assert saved["mime_type"] == result["mime_type"] == "image/gif"
    assert result["storage_key"].endswith(".gif")
    assert (result["width"], result["height"]) == (12, 8)
    assert result["sha256"] == hashlib.sha256(animated_gif).hexdigest()
    if storage != "hot_url":
        assert saved["qiniu_storage_enabled"] == (storage == "cdn")
    with Image.open(BytesIO(saved["content"])) as image:
        assert image.n_frames == 2
        assert image.info["loop"] == 0
        assert image.info["duration"] == 100
        image.seek(1)
        assert image.info["duration"] == 200
    # Output support must not silently broaden reference upload admission.
    assert "image/gif" not in image_uploads._allowed_mime_types()


@pytest.mark.parametrize("header", [b"GIF87a", b"GIF89a"])
def test_gif_signature_and_base64_decode(animated_gif, header):
    content = header + animated_gif[6:]
    result = image_generation._decode_base64_image(base64.b64encode(content).decode())
    assert result.content == content
    assert result.mime_type == "image/gif"
    metadata = image_uploads._extract_image_metadata(content, "image/png")
    assert metadata.mime_type == "image/gif"
    assert (metadata.width, metadata.height) == (12, 8)


def test_gif_export_keeps_extension_and_bytes(monkeypatch, animated_gif):
    monkeypatch.setattr(catalog_exports, "read_export_image", lambda url: (animated_gif, "image/gif"))
    with catalog_exports._build_export_archive([("IMG1", "https://cdn.example/asset")]) as archive:
        with ZipFile(archive) as result:
            assert result.namelist() == ["001-IMG1.gif"]
            assert result.read("001-IMG1.gif") == animated_gif
    assert catalog_exports.export_file_extension("https://cdn.example/1.GIF?download=1", None) == ".gif"
    assert image_uploads._guess_media_mime_from_url("https://cdn.example/1.gif") == "image/gif"
    assert image_generation._guess_media_mime_from_url("https://cdn.example/1.gif") == "image/gif"
