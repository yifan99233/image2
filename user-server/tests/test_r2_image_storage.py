from datetime import UTC, datetime, timedelta

from app.api.routes.catalog_serializers import serialize_asset
from app.core.config import settings
from app.services import image_generation, image_uploads


MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_upstream_r2_url_is_preserved_separately_from_downloaded_bytes(monkeypatch):
    downloaded: list[str] = []

    def fake_download(url, _timeout):
        downloaded.append(url)
        return image_generation.GeneratedImage(content=MINIMAL_PNG, mime_type="image/png")

    monkeypatch.setattr(image_generation, "_download_image", fake_download)
    image = image_generation._extract_openai_images_result(
        {
            "data": [
                {
                    "url": "https://origin.example/image.png",
                    "r2_url": "https://pub-example.r2.dev/generated/image.png",
                }
            ]
        },
        timeout=10,
    )

    assert downloaded == ["https://pub-example.r2.dev/generated/image.png"]
    assert image.hot_url == "https://pub-example.r2.dev/generated/image.png"


def test_hot_generated_image_only_writes_the_local_backup(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        image_uploads,
        "_store_local_image",
        lambda **kwargs: calls.append(f"local:{kwargs['storage_key']}") or "https://magic.example/local.png",
    )
    monkeypatch.setattr(
        image_uploads,
        "_store_image",
        lambda **_kwargs: calls.append("ordinary") or "https://cdn.example/ordinary.png",
    )

    stored = image_uploads.store_generated_image_object(
        user_id=7,
        content=MINIMAL_PNG,
        mime_type="image/png",
        hot_url="https://pub-example.r2.dev/generated/image.png",
    )

    assert len(calls) == 1
    assert calls[0].startswith("local:generated/7/")
    assert stored["url"] == "https://magic.example/local.png"
    assert stored["local_url"] == "https://magic.example/local.png"
    assert stored["r2_url"] == "https://pub-example.r2.dev/generated/image.png"
    assert stored["r2_expires_at"] > datetime.now(UTC)


def test_asset_serializer_falls_back_after_r2_ttl():
    local_url = "https://magic.example/local.png"
    hot_url = "https://pub-example.r2.dev/generated/image.png"
    future = datetime.now(UTC) + timedelta(minutes=5)
    expired = datetime.now(UTC) - timedelta(minutes=5)

    hot = serialize_asset(local_url, local_url=local_url, r2_url=hot_url, r2_expires_at=future)
    cold = serialize_asset(local_url, local_url=local_url, r2_url=hot_url, r2_expires_at=expired)

    assert hot["url"] == hot_url
    assert cold["url"] == local_url


def test_prepare_r2_upload_uses_presigned_put_without_exposing_credentials(monkeypatch):
    class FakeR2Client:
        def presigned_put_object(self, bucket, object_key, expires):
            assert bucket == "image-bucket"
            assert object_key.startswith("image2-staging/9/")
            assert expires.total_seconds() == settings.r2_upload_expires_seconds
            return "https://r2-upload.example/presigned"

    monkeypatch.setattr(settings, "r2_enabled", True)
    monkeypatch.setattr(settings, "r2_endpoint", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setattr(settings, "r2_access_key_id", "access-key")
    monkeypatch.setattr(settings, "r2_secret_access_key", "secret-key")
    monkeypatch.setattr(settings, "r2_bucket", "image-bucket")
    monkeypatch.setattr(settings, "r2_public_base_url", "https://pub-example.r2.dev")
    monkeypatch.setattr(image_uploads, "_r2_client", lambda: FakeR2Client())

    result = image_uploads.prepare_r2_upload(
        user_id=9,
        filename="input.png",
        mime_type="image/png",
        size_bytes=len(MINIMAL_PNG),
    )

    assert result["upload_url"] == "https://r2-upload.example/presigned"
    assert result["upload_method"] == "PUT"
    assert result["r2_url"].startswith("https://pub-example.r2.dev/image2-staging/9/")
    assert "access-key" not in result["upload_url"]
    assert "secret-key" not in result["upload_url"]
