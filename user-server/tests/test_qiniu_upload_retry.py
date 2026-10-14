from io import BytesIO
from http.client import IncompleteRead
from urllib import error as urlerror

import pytest

from app.core.exceptions import BusinessError
from app.services import image_uploads


class SuccessfulResponse:
    status = 200

    def __init__(self, content=b"generated-image-bytes"):
        self.headers = {"Content-Length": str(len(content))}
        self.body = BytesIO(content)

    def read(self, size):
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def qiniu_target() -> image_uploads.StorageTarget:
    return image_uploads.StorageTarget(
        name="test-qiniu",
        provider="qiniu",
        bucket="test-bucket",
        public_base_url="https://cdn.example.com",
        key_prefix="image2-assets",
        access_key="test-access-key",
        secret_key="test-secret-key",
        upload_host="https://upload.qiniup.com",
    )


@pytest.mark.parametrize(
    "error_factory",
    (
        lambda: urlerror.URLError(ConnectionResetError(104, "Connection reset by peer")),
        lambda: TimeoutError("The read operation timed out"),
        lambda: urlerror.HTTPError(
            "https://upload.qiniup.com",
            504,
            "Gateway Time-out",
            {"X-Reqid": "test-request-id"},
            BytesIO(b'{"error":"gateway timeout"}'),
        ),
    ),
)
def test_qiniu_upload_retries_transient_error(monkeypatch, error_factory):
    attempts = 0
    sleep_delays: list[float] = []

    def fake_urlopen(request, timeout):
        nonlocal attempts
        if request.get_method() == "GET":
            raise urlerror.HTTPError(request.full_url, 404, "Not found", {}, None)
        attempts += 1
        assert request.full_url == "https://upload.qiniup.com"
        assert timeout == 60
        if attempts == 1:
            raise error_factory()
        return SuccessfulResponse()

    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", fake_urlopen)
    monkeypatch.setattr(image_uploads.time, "sleep", sleep_delays.append)

    url = image_uploads._store_in_qiniu(
        target=qiniu_target(),
        content=b"generated-image-bytes",
        storage_key="image2-assets/generated/20/result.png",
        mime_type="image/png",
    )

    assert url == "https://cdn.example.com/image2-assets/generated/20/result.png"
    assert attempts == 2
    assert sleep_delays == [1.0]


def test_qiniu_upload_stops_after_bounded_transient_retries(monkeypatch):
    attempts = 0
    sleep_delays: list[float] = []

    def fake_urlopen(request, timeout):
        nonlocal attempts
        if request.get_method() == "GET":
            raise urlerror.HTTPError(request.full_url, 404, "Not found", {}, None)
        attempts += 1
        raise urlerror.URLError(ConnectionResetError(104, "Connection reset by peer"))

    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", fake_urlopen)
    monkeypatch.setattr(image_uploads.time, "sleep", sleep_delays.append)

    with pytest.raises(BusinessError) as caught:
        image_uploads._store_in_qiniu(
            target=qiniu_target(),
            content=b"generated-image-bytes",
            storage_key="image2-assets/generated/20/result.png",
            mime_type="image/png",
        )

    assert caught.value.code == 50020
    assert attempts == image_uploads.QINIU_UPLOAD_MAX_ATTEMPTS == 3
    assert sleep_delays == [1.0, 2.0]


def test_qiniu_upload_treats_existing_object_after_retry_as_success(monkeypatch):
    attempts = 0
    sleep_delays: list[float] = []

    def fake_urlopen(request, timeout):
        nonlocal attempts
        if request.get_method() == "GET":
            if attempts == 2:
                return SuccessfulResponse()
            raise TimeoutError()
        attempts += 1
        if attempts == 1:
            raise urlerror.URLError(ConnectionResetError(104, "Connection reset by peer"))
        raise urlerror.HTTPError(
            request.full_url,
            image_uploads.QINIU_OBJECT_EXISTS_STATUS,
            "File exists",
            {"X-Reqid": "test-request-id"},
            BytesIO(b'{"error":"file exists"}'),
        )

    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", fake_urlopen)
    monkeypatch.setattr(image_uploads.time, "sleep", sleep_delays.append)

    url = image_uploads._store_in_qiniu(
        target=qiniu_target(),
        content=b"generated-image-bytes",
        storage_key="image2-assets/generated/20/result.png",
        mime_type="image/png",
    )

    assert url == "https://cdn.example.com/image2-assets/generated/20/result.png"
    assert attempts == 2
    assert sleep_delays == [1.0]


def test_qiniu_upload_does_not_retry_authentication_error(monkeypatch):
    attempts = 0
    sleep_delays: list[float] = []

    def fake_urlopen(request, timeout):
        nonlocal attempts
        if request.get_method() == "GET":
            raise urlerror.HTTPError(request.full_url, 404, "Not found", {}, None)
        attempts += 1
        raise urlerror.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {"X-Reqid": "test-request-id"},
            BytesIO(b'{"error":"bad token"}'),
        )

    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", fake_urlopen)
    monkeypatch.setattr(image_uploads.time, "sleep", sleep_delays.append)

    with pytest.raises(BusinessError) as caught:
        image_uploads._store_in_qiniu(
            target=qiniu_target(),
            content=b"generated-image-bytes",
            storage_key="image2-assets/generated/20/result.png",
            mime_type="image/png",
        )

    assert caught.value.code == 50020
    assert attempts == 1
    assert sleep_delays == []


@pytest.mark.parametrize("visible_on_attempt", [1, 3])
def test_timeout_recovers_only_after_stored_bytes_are_verified(monkeypatch, visible_on_attempt):
    attempts = 0

    def fake_urlopen(request, timeout):
        nonlocal attempts
        if request.get_method() == "POST":
            attempts += 1
            raise TimeoutError()
        assert timeout == 10
        if attempts < visible_on_attempt:
            raise urlerror.HTTPError(request.full_url, 404, "Not found", {}, None)
        return SuccessfulResponse()

    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", fake_urlopen)
    monkeypatch.setattr(image_uploads.time, "sleep", lambda _: None)
    assert image_uploads._store_in_qiniu(
        target=qiniu_target(), content=b"generated-image-bytes",
        storage_key="result.png", mime_type="image/png",
    ) == "https://cdn.example.com/result.png"
    assert attempts == visible_on_attempt


@pytest.mark.parametrize("stored", [b"truncated", b"X" * 21, b"generated-image-bytesEXTRA"])
@pytest.mark.parametrize("has_length", [True, False])
def test_verification_rejects_incomplete_or_different_object(monkeypatch, stored, has_length):
    response = SuccessfulResponse(stored)
    if not has_length:
        response.headers = {}
    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", lambda *args, **kwargs: response)
    assert not image_uploads._qiniu_object_matches(
        target=qiniu_target(), storage_key="result.png", content=b"generated-image-bytes",
    )


def test_existing_object_with_different_bytes_is_not_success(monkeypatch):
    attempts = 0

    def fake_urlopen(request, timeout):
        nonlocal attempts
        if request.get_method() == "GET":
            return SuccessfulResponse(b"wrong-image")
        attempts += 1
        if attempts == 1:
            raise TimeoutError()
        raise urlerror.HTTPError(request.full_url, 614, "File exists", {}, None)

    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", fake_urlopen)
    monkeypatch.setattr(image_uploads.time, "sleep", lambda _: None)
    with pytest.raises(BusinessError):
        image_uploads._store_in_qiniu(
            target=qiniu_target(), content=b"generated-image-bytes",
            storage_key="result.png", mime_type="image/png",
        )


def test_verification_handles_broken_response(monkeypatch):
    response = SuccessfulResponse()

    def broken_read(size):
        raise IncompleteRead(b"partial", 21)

    response.read = broken_read
    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", lambda *args, **kwargs: response)
    assert not image_uploads._qiniu_object_matches(
        target=qiniu_target(), storage_key="result.png", content=b"generated-image-bytes",
    )


@pytest.mark.parametrize("size,expected", [
    (0, "Fto5o-5ea0sNMlW_75VgGJCv2AcJ"),
    (4194304, "FuwQ-vpd56Izwiom1JHzCIdrQa4_"),
    (4194305, "lieGn00gWdbfwEIHaUpzu4drHeun"),
])
def test_qiniu_etag_block_boundaries(size, expected):
    assert image_uploads._qiniu_content_etag(b"a" * size) == expected


def test_matching_qiniu_etag_avoids_downloading_body(monkeypatch):
    response = SuccessfulResponse(b"")
    response.headers["ETag"] = '"Fto5o-5ea0sNMlW_75VgGJCv2AcJ"'

    def unexpected_read(size):
        pytest.fail("Verified ETag must not download the object")

    response.read = unexpected_read
    monkeypatch.setattr(image_uploads.urlrequest, "urlopen", lambda *args, **kwargs: response)
    assert image_uploads._qiniu_object_matches(target=qiniu_target(), storage_key="result.png", content=b"")
