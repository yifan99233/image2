import pytest

from app.services import image_generation
from app.services.image_generation import (
    GenerationModelConfig,
    _openai_chat_completions_body,
    _openai_size,
    generate_image,
)


A_SERIES_IMAGE_SIZES = [
    ("1:1.414", "1k", "1024x1440"),
    ("1:1.414", "2k", "1456x2048"),
    ("1:1.414", "4k", "2720x3840"),
    ("1.414:1", "1k", "1440x1024"),
    ("1.414:1", "2k", "2048x1456"),
    ("1.414:1", "4k", "3840x2720"),
]

A_SERIES_SDK_DIMENSIONS = [
    ("1:1.414", "1k", (724, 1024)),
    ("1:1.414", "2k", (1448, 2048)),
    ("1:1.414", "4k", (2897, 4096)),
    ("1.414:1", "1k", (1024, 724)),
    ("1.414:1", "2k", (2048, 1448)),
    ("1.414:1", "4k", (4096, 2897)),
]


@pytest.mark.parametrize(("aspect_ratio", "resolution", "expected_size"), A_SERIES_IMAGE_SIZES)
def test_images_api_forwards_a_series_size(monkeypatch, aspect_ratio, resolution, expected_size):
    captured: dict = {}

    def fake_post_json(_url, body, _headers, _timeout):
        captured["body"] = body
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    config = GenerationModelConfig(
        "openai",
        "OpenAI",
        "https://api.openai.com/v1",
        "api",
        "test-key",
        "bearer",
        120,
        "gpt-image-2",
    )

    generate_image(config, "生成 A 系列图片", None, resolution, aspect_ratio)

    assert captured["body"]["size"] == expected_size


@pytest.mark.parametrize(("aspect_ratio", "resolution", "expected_dimensions"), A_SERIES_SDK_DIMENSIONS)
def test_sdk_forwards_a_series_dimensions(aspect_ratio, resolution, expected_dimensions):
    config = GenerationModelConfig(
        provider_code="google-3-1-image-sdk",
        provider_name="Google 3.1 Image",
        base_url="https://agent4.shyfai.cn/v1",
        access_mode="sdk",
        api_key="test-key",
        auth_type="bearer",
        timeout_seconds=120,
        vendor_model="gemini-3.1-flash-image",
    )

    body = _openai_chat_completions_body(config, "生成 A 系列图片", resolution, aspect_ratio)

    assert body["aspect_ratio"] == aspect_ratio
    assert (body["width"], body["height"]) == expected_dimensions
    long_side = max(body["width"], body["height"])
    short_side = min(body["width"], body["height"])
    assert abs(long_side / short_side - 1.414) < 0.001


@pytest.mark.parametrize(("aspect_ratio", "resolution", "expected_size"), A_SERIES_IMAGE_SIZES)
def test_a_series_size_mapping_and_provider_limit(aspect_ratio, resolution, expected_size):
    size = _openai_size(resolution, aspect_ratio)

    assert size == expected_size
    width, height = (int(item) for item in size.split("x"))
    assert width % 16 == 0
    assert height % 16 == 0
    assert abs(max(width, height) / min(width, height) - 1.414) / 1.414 < 0.006
    if resolution == "4k":
        assert max(width, height) <= 3840
