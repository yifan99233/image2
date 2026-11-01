import pytest

from app.services import image_generation
from app.services.image_generation import GeneratedImage, GenerationModelConfig, generate_image
from app.services.image_provider_models import BANANA_IMAGES_API_MODELS


LEGACY_BANANA_MODELS = sorted(model for model in BANANA_IMAGES_API_MODELS if not model.endswith(("-adx1", "-adx2")))
BANANA_MODEL_NAMES = LEGACY_BANANA_MODELS + [
    f"{model}-cdn" for model in LEGACY_BANANA_MODELS
]


def config_for(model: str) -> GenerationModelConfig:
    return GenerationModelConfig(
        "agent-adx", "Agent ADX", "https://api.example.com/v1", "api",
        "test-key", "bearer", 300, model,
    )


@pytest.mark.parametrize("model", ["nano-banana-2-adx1", "nano-banana-2.1-adx1", "nano-banana-2-adx2", "nano-banana-2.1-adx2"])
@pytest.mark.parametrize("resolution", ["1k", "2k", "4k"])
def test_adx1_banana_uses_images_api_with_structured_resolution(monkeypatch, model, resolution):
    captured = {}

    def post(url, body, headers, timeout):
        captured.update(url=url, body=body)
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_json", post)
    generated = generate_image(config_for(model), "test", None, resolution, "1:1", quality="high")
    assert generated.content == b"image"
    assert captured["url"] == "https://api.example.com/v1/images/generations"
    assert captured["body"] == {
        "model": model, "prompt": "test", "resolution": resolution, "aspect_ratio": "1:1",
    }


@pytest.mark.parametrize("model", BANANA_MODEL_NAMES)
@pytest.mark.parametrize("resolution,ratio", [("1k", "21:9"), ("2k", "4:3"), ("4k", "9:16")])
def test_banana_generation_preserves_structured_dimensions(monkeypatch, model, resolution, ratio):
    captured = {}

    def post(url, body, headers, timeout):
        captured.update(url=url, body=body, headers=headers)
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_json", post)
    generated = generate_image(
        config_for(model), "生一张图", None, resolution, ratio,
        quality="high", client_reference="IMG-BANANA-TEST",
    )

    assert generated.content == b"image"
    assert captured["url"] == "https://api.example.com/v1/images/generations"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"] == {
        "model": model, "prompt": "生一张图",
        "resolution": resolution, "aspect_ratio": ratio,
        "client_reference": "IMG-BANANA-TEST",
    }


@pytest.mark.parametrize("model", BANANA_MODEL_NAMES)
def test_banana_edit_preserves_dimensions_and_all_reference_images(monkeypatch, model):
    source_images = [GeneratedImage(b"one", "image/png"), GeneratedImage(b"two", "image/png")]
    captured = {}
    monkeypatch.setattr(image_generation, "_input_images_from_values", lambda *_args: source_images)

    def post(url, fields, files, config, timeout):
        captured.update(url=url, fields=fields, files=files)
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_multipart", post)
    generate_image(config_for(model), "保留主体，改成海边背景", ["one", "two"], "2k", "21:9")

    assert captured["url"] == "https://api.example.com/v1/images/edits"
    assert captured["fields"] == {
        "model": model, "prompt": "保留主体，改成海边背景",
        "resolution": "2k", "aspect_ratio": "21:9",
    }
    assert [file[3] for file in captured["files"]] == [b"one", b"two"]


@pytest.mark.parametrize("model", ["nano-banana-2-adx1", "nano-banana-2.1-adx1", "nano-banana-2-adx2", "nano-banana-2.1-adx2"])
@pytest.mark.parametrize("ratio", ["auto", "1:1", "1:4", "4:1", "1:8", "8:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"])
def test_adx1_banana_edit_keeps_requested_tier_ratio_and_reference_order(monkeypatch, model, ratio):
    sources = [GeneratedImage(b"first", "image/png"), GeneratedImage(b"second", "image/jpeg")]
    monkeypatch.setattr(image_generation, "_input_images_from_values", lambda *_: sources)
    captured = {}
    def post(url, fields, files, config, timeout):
        captured.update(url=url, fields=fields, files=files)
        return {"data": [{"b64_json": "aW1hZ2U="}]}
    monkeypatch.setattr(image_generation, "_post_multipart", post)
    generate_image(config_for(model), "edit", ["a", "b"], "4k", ratio)
    assert captured["url"].endswith("/v1/images/edits")
    assert captured["fields"] == {"model": model, "prompt": "edit", "resolution": "4k", "aspect_ratio": ratio}
    assert [f[3] for f in captured["files"]] == [b"first", b"second"]


@pytest.mark.parametrize("model", ["gpt-image-2-adx1", "gpt-image-2.5-flare-adx1", "gpt-image-2.5-sunburst-adx1"])
@pytest.mark.parametrize("edit", [False, True])
@pytest.mark.parametrize("resolution,ratio,size", [("1k", "16:9", "1536x864"), ("2k", "16:9", "2048x1152"), ("4k", "16:9", "3840x2160"), ("4k", "auto", "auto")])
def test_adx1_native_preserves_output_tier_and_quality(monkeypatch, model, edit, resolution, ratio, size):
    captured = {}
    monkeypatch.setattr(image_generation, "_input_images_from_values", lambda *_: [GeneratedImage(b"ref", "image/png")] if edit else [])
    def post_json(url, fields, headers, timeout):
        captured.update(url=url, fields=fields)
        return {"data": [{"b64_json": "aW1hZ2U="}]}
    def post_multipart(url, fields, files, config, timeout):
        assert files[0][3] == b"ref"
        return post_json(url, fields, {}, timeout)
    monkeypatch.setattr(image_generation, "_post_json", post_json)
    monkeypatch.setattr(image_generation, "_post_multipart", post_multipart)
    generate_image(config_for(model), "test", ["ref"] if edit else None, resolution, ratio, quality="high")
    assert captured["url"].endswith("/images/edits" if edit else "/images/generations")
    assert captured["fields"] == {"model": model, "prompt": "test", "size": size, "quality": "high", "resolution": resolution}

@pytest.mark.parametrize("model", ["gpt-image-2-adx2", "gpt-image-2.5-flare-adx2"])
@pytest.mark.parametrize("edit", [False, True])
@pytest.mark.parametrize("resolution", ["1k", "2k", "4k"])
def test_adx2_uses_independent_tier_ratio_and_quality(monkeypatch, model, edit, resolution):
    captured = {}
    monkeypatch.setattr(image_generation, "_input_images_from_values", lambda *_: [GeneratedImage(b"ref", "image/png")] if edit else [])
    def post_json(url, fields, headers, timeout):
        captured.update(url=url, fields=fields)
        return {"data": [{"b64_json": "aW1hZ2U="}]}
    def post_multipart(url, fields, files, config, timeout):
        assert files[0][3] == b"ref"
        return post_json(url, fields, {}, timeout)
    monkeypatch.setattr(image_generation, "_post_json", post_json)
    monkeypatch.setattr(image_generation, "_post_multipart", post_multipart)
    generate_image(config_for(model), "test", ["ref"] if edit else None, resolution, "16:9", quality="high")
    assert captured["url"].endswith("/images/edits" if edit else "/images/generations")
    assert captured["fields"] == {"model":model,"prompt":"test","resolution":resolution,"aspect_ratio":"16:9","quality":"high"}
