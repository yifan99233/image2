from pathlib import Path
from types import SimpleNamespace


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


def _fake_store_in_minio(*, content: bytes, storage_key: str, mime_type: str) -> str:
    return f"https://magic.shyfai.com/image2-assets/{storage_key}"


def _fake_store_in_qiniu(*, content: bytes, storage_key: str, mime_type: str, target=None) -> str:
    return f"https://image-cdn.example.com/{storage_key}"


async def _mock_minio_storage(monkeypatch) -> None:
    monkeypatch.setattr("app.services.image_uploads._store_image", _fake_store_in_minio)


async def _register_and_login(client) -> str:
    await client.post(
        "/auth/register",
        json={"username": "uploader", "email": "uploader@example.com", "password": "strong-pass-123"},
    )
    login_response = await client.post(
        "/auth/login",
        json={"username": "uploader", "password": "strong-pass-123"},
    )
    return login_response.json()["data"]["access_token"]


async def test_upload_image_requires_auth(client):
    response = await client.post(
        "/uploads/images",
        files={"image": ("sample.png", MINIMAL_PNG, "image/png")},
    )

    assert response.status_code == 401


async def test_upload_image_returns_asset(client, monkeypatch):
    await _mock_minio_storage(monkeypatch)
    token = await _register_and_login(client)

    response = await client.post(
        "/uploads/images",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("sample.png", MINIMAL_PNG, "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["code"] == 0
    assert payload["data"]["mime_type"] == "image/png"
    assert payload["data"]["width"] == 1
    assert payload["data"]["height"] == 1
    assert payload["data"]["url"].startswith("https://magic.shyfai.com/image2-assets/images/")


async def test_signed_url_returns_owned_asset_url(client, monkeypatch):
    await _mock_minio_storage(monkeypatch)
    token = await _register_and_login(client)
    upload_response = await client.post(
        "/uploads/images",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("sample.png", MINIMAL_PNG, "image/png")},
    )
    asset = upload_response.json()["data"]

    response = await client.get(
        f"/uploads/images/{asset['id']}/signed-url",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["url"] == asset["url"]


def test_qiniu_storage_uses_image_prefix(monkeypatch):
    from app.core.config import settings
    from app.services import image_uploads

    monkeypatch.setattr(settings, "qiniu_image_prefix", "image2-assets")
    monkeypatch.setattr(image_uploads, "_store_in_qiniu", lambda **kwargs: _fake_store_in_qiniu(**kwargs))

    storage_key = image_uploads._image_storage_key(
        Path("generated") / "7",
        "example.png",
        qiniu_storage_enabled=True,
    )
    url = image_uploads._store_image(
        content=MINIMAL_PNG,
        storage_key=storage_key,
        mime_type="image/png",
        qiniu_storage_enabled=True,
    )

    assert storage_key == "image2-assets/generated/7/example.png"
    assert url == "https://image-cdn.example.com/image2-assets/generated/7/example.png"


def test_admin_toggle_disables_qiniu_even_if_env_is_qiniu(monkeypatch):
    from app.core.config import settings
    from app.services import image_uploads

    monkeypatch.setattr(settings, "upload_storage_provider", "qiniu")
    monkeypatch.setattr(image_uploads, "_store_in_minio", lambda **kwargs: _fake_store_in_minio(**kwargs))

    storage_key = image_uploads._image_storage_key(
        Path("generated") / "7",
        "example.png",
        qiniu_storage_enabled=False,
    )
    url = image_uploads._store_image(
        content=MINIMAL_PNG,
        storage_key=storage_key,
        mime_type="image/png",
        qiniu_storage_enabled=False,
    )

    assert storage_key == "generated/7/example.png"
    assert url == "https://magic.shyfai.com/image2-assets/generated/7/example.png"


def test_named_qiniu_target_selects_its_own_cdn(monkeypatch):
    from app.core.config import settings
    from app.services import image_uploads

    monkeypatch.setattr(settings, "image_storage_target", "qiniu-secondary")
    monkeypatch.setattr(settings, "image_storage_targets_json", '{"qiniu-primary":{"provider":"qiniu","bucket":"primary","cdn_base_url":"https://primary-cdn.example.com","key_prefix":"primary","access_key":"primary-key","secret_key":"primary-secret","upload_host":"https://upload.qiniup.com"},"qiniu-secondary":{"provider":"qiniu","bucket":"secondary","cdn_base_url":"https://secondary-cdn.example.com","key_prefix":"secondary","access_key":"secondary-key","secret_key":"secondary-secret","upload_host":"https://upload.qiniup.com"}}')
    monkeypatch.setattr(image_uploads, "_store_in_qiniu", lambda **kwargs: f"{kwargs['target'].public_base_url}/{kwargs['storage_key']}")

    storage_key = image_uploads._image_storage_key(Path("generated") / "7", "example.png")
    url = image_uploads._store_image(content=MINIMAL_PNG, storage_key=storage_key, mime_type="image/png")

    assert storage_key == "secondary/generated/7/example.png"
    assert url == "https://secondary-cdn.example.com/secondary/generated/7/example.png"


async def test_qiniu_upload_keeps_a_local_copy_for_upstream_model_downloads(monkeypatch):
    from app.services import image_uploads

    qiniu_target = image_uploads.StorageTarget(
        name="test-qiniu",
        provider="qiniu",
        bucket="test-bucket",
        public_base_url="https://cdn.example.com",
        key_prefix="image2-assets",
        access_key="test-access-key",
        secret_key="test-secret-key",
        upload_host="https://upload.qiniup.com",
    )
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(image_uploads, "_active_storage_target", lambda **_: qiniu_target)
    monkeypatch.setattr(
        image_uploads,
        "_store_in_qiniu",
        lambda **kwargs: stored.append(("qiniu", kwargs["storage_key"]))
        or f"https://cdn.example.com/{kwargs['storage_key']}",
    )
    monkeypatch.setattr(
        image_uploads,
        "_store_local_image",
        lambda **kwargs: stored.append(("minio", kwargs["storage_key"]))
        or f"https://magic.shagentai.com/image2-assets/{kwargs['storage_key']}",
    )

    class FakeDB:
        def add(self, asset):
            self.asset = asset

        async def commit(self):
            return None

        async def refresh(self, asset):
            return None

    asset = await image_uploads._save_uploaded_content(
        db=FakeDB(),
        current_user=SimpleNamespace(id=7, site_id=1),
        content=MINIMAL_PNG,
        original_filename="sample.png",
        submitted_mime_type="image/png",
        qiniu_storage_enabled=True,
    )

    assert stored[0][0] == "qiniu"
    assert stored[1][0] == "minio"
    assert stored[0][1].startswith("image2-assets/images/7/")
    assert stored[1][1].startswith("images/7/")
    assert asset.url.startswith("https://cdn.example.com/image2-assets/images/7/")
    assert asset.local_url.startswith("https://magic.shagentai.com/image2-assets/images/7/")
    assert image_uploads.effective_asset_url(asset) == asset.url
