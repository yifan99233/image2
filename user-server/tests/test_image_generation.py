import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from app.api.routes import catalog
from app.core.exceptions import BusinessError
from app.services import image_generation, text_generation
from app.services.image_generation import (
    GenerationModelConfig,
    MODEL_IMAGE_CAPACITY_MESSAGE,
    MODEL_TIMEOUT_CODE,
    MODEL_TIMEOUT_MESSAGE,
    RESULT_DOWNLOAD_TIMEOUT_CODE,
    RESULT_DOWNLOAD_TIMEOUT_MESSAGE,
    _attach_provider_trace,
    _extract_chat_completions_image_result,
    _generation_prompt,
    _input_image_from_value,
    _openai_chat_completions_body,
    _openai_size,
    _provider_error_message,
    generate_image,
)
from app.services.image_parameters import normalize_image_quality


def test_extract_chat_completions_markdown_data_url_image():
    png_1x1 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    payload = {
        "choices": [
            {
                "message": {
                    "content": f"![Generated Image](data:image/png;base64,{png_1x1})\n\n",
                }
            }
        ]
    }

    image = _extract_chat_completions_image_result(payload, timeout=1)

    assert image.mime_type == "image/png"
    assert image.content.startswith(b"\x89PNG")


def test_provider_trace_keeps_request_id_and_redacted_snapshot():
    image = _attach_provider_trace(
        image_generation.GeneratedImage(content=b"image", mime_type="image/png"),
        {
            "_image2_trace": {
                "request_id": "api-trace-123",
                "http_status": 200,
                "request_snapshot": {"endpoint": "http://image-api/v1/images/generations", "body": {"model": "gpt-image-2"}},
                "response_summary": {"request_id": "api-trace-123", "data_count": 2},
            }
        },
    )

    assert image.provider_request_id == "api-trace-123"
    assert image.provider_http_status == 200
    assert image.provider_request_snapshot == {"endpoint": "http://image-api/v1/images/generations", "body": {"model": "gpt-image-2"}}
    assert image.provider_response_summary == {"request_id": "api-trace-123", "data_count": 2}


def test_generation_prompt_for_input_image_requires_editing_from_source():
    prompt = _generation_prompt("帮我改成黑白风格", "1k", "1:1", has_input_image=True)

    assert "图像编辑任务" in prompt
    assert "以随附输入图片作为主要视觉参考" in prompt
    assert "不要脱离原图重新创作" in prompt
    assert "用户修改要求：帮我改成黑白风格" in prompt


def test_input_image_from_value_rejects_local_upload_path():
    with pytest.raises(BusinessError):
        _input_image_from_value("/uploads/images/5/input.png", timeout=1)


@pytest.mark.parametrize("vendor_model,resolution,image_config", [
    ("nano-banana", "1k", {"aspectRatio": "9:16", "imageSize": "1K"}),
    ("nano-banana", "2k", {"aspectRatio": "9:16", "imageSize": "2K"}),
    ("nano-banana", "4k", {"aspectRatio": "9:16", "imageSize": "4K"}),
    ("nano-banana-pro", "1k", {"aspectRatio": "9:16", "imageSize": "1K"}),
    ("nano-banana-pro", "2k", {"aspectRatio": "9:16", "imageSize": "2K"}),
    ("nano-banana-pro", "4k", {"aspectRatio": "9:16", "imageSize": "4K"}),
])
@pytest.mark.parametrize("input_image", [None, "data:image/png;base64,aW1hZ2U="])
def test_native_banana_generates_and_edits_with_structured_dimensions(monkeypatch, vendor_model, resolution, image_config, input_image):
    captured = {}

    def fake_post_json(url, body, headers, timeout):
        captured.update(url=url, body=body)
        return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "aW1hZ2U="}}]}}]}

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    config = GenerationModelConfig("agent5-gemini-banana", "Gemini Banana", "https://agent5.shyfai.cn", "api", "test-key", "bearer", 225, vendor_model)

    image = generate_image(config, "生成竖版图片", input_image, resolution, "9:16")

    assert captured["url"] == f"https://agent5.shyfai.cn/v1beta/models/{vendor_model}:generateContent?key=test-key"
    assert captured["body"]["generationConfig"] == {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": image_config}
    parts = captured["body"]["contents"][0]["parts"]
    assert len(parts) == (2 if input_image else 1)
    if input_image:
        assert parts[1] == {"inlineData": {"mimeType": "image/png", "data": "aW1hZ2U="}}
    assert image.content == b"image"
    assert image.mime_type == "image/png"


def test_native_gemini_keeps_unrelated_models_request_contract():
    assert image_generation._gemini_generation_config("custom-gemini", "4k", "9:16") == {"responseModalities": ["TEXT", "IMAGE"]}


def test_native_gemini_25_image_does_not_send_image_size():
    assert image_generation._gemini_generation_config("gemini-2.5-flash-image", "1k", "9:16") == {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}


def test_openai_chat_completions_body_includes_gemini_extra_body_fields():
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
    content = [
        {"type": "text", "text": "将这张图片转换为高级黑白风格。"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]

    body = _openai_chat_completions_body(config, content, "1k", "1:1")

    assert body["model"] == "gemini-3.1-flash-image"
    assert body["messages"][0]["content"] == content
    assert body["aspect_ratio"] == "1:1"
    assert body["width"] == 1024
    assert body["height"] == 1024


def test_gpt_image_generation_omits_response_format(monkeypatch):
    captured: dict = {}

    def fake_post_json(url, body, headers, timeout):
        captured["url"] = url
        captured["body"] = body
        return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="}]}

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    config = GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 120, "gpt-image-2")

    image = generate_image(
        config,
        "帮我生一张二次元图片",
        None,
        "1k",
        "1:1",
        quality="high",
        client_reference="IMG-CLIENT-123",
    )

    assert image.mime_type == "image/png"
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert captured["body"]["model"] == "gpt-image-2"
    assert captured["body"]["prompt"] == "帮我生一张二次元图片"
    assert captured["body"]["client_reference"] == "IMG-CLIENT-123"
    assert captured["body"]["quality"] == "high"
    assert set(captured["body"]) == {"model", "prompt", "size", "quality", "client_reference"}
    assert "response_format" not in captured["body"]
    assert "n" not in captured["body"]
    assert "disable_retry" not in captured["body"]


@pytest.mark.parametrize(
    ("aspect_ratio", "expected_size"),
    [
        ("1:1", "1024x1024"),
        ("3:4", "864x1152"),
        ("9:16", "864x1536"),
        ("21:9", "1792x768"),
    ],
)
def test_gpt_image_generation_forwards_selected_aspect_ratio_size(monkeypatch, aspect_ratio, expected_size):
    captured: dict = {}

    def fake_post_json(_url, body, _headers, _timeout):
        captured["body"] = body
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    config = GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 120, "gpt-image-2")

    generate_image(config, "生成指定比例图片", None, "1k", aspect_ratio)

    assert captured["body"]["size"] == expected_size


def test_gpt_image_generation_does_not_forward_internal_disable_retry(monkeypatch):
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
        disable_retry=True,
    )

    generate_image(config, "生成图片", None, "1k", "1:1")

    assert "disable_retry" not in captured["body"]


def test_gpt_image_edit_omits_response_format(monkeypatch):
    captured: dict = {}

    def fake_post_multipart(url, fields, files, config, timeout):
        captured["url"] = url
        captured["fields"] = fields
        captured["files"] = files
        return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="}]}

    monkeypatch.setattr(image_generation, "_post_multipart", fake_post_multipart)
    config = GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 120, "gpt-image-2")

    image = generate_image(
        config,
        "改成二次元风格",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
        "1k",
        "1:1",
        quality="medium",
    )

    assert image.mime_type == "image/png"
    assert captured["url"] == "https://api.openai.com/v1/images/edits"
    assert captured["fields"]["model"] == "gpt-image-2"
    assert captured["fields"]["prompt"] == "改成二次元风格"
    assert captured["fields"]["quality"] == "medium"
    assert set(captured["fields"]) == {"model", "prompt", "size", "quality"}
    assert "response_format" not in captured["fields"]
    assert "n" not in captured["fields"]
    assert "disable_retry" not in captured["fields"]
    assert len(captured["files"]) == 1
    assert captured["files"][0][0] == "image"


def test_image_quality_normalization_defaults_and_rejects_unknown_values():
    assert normalize_image_quality(None) == "auto"
    assert normalize_image_quality(" HIGH ") == "high"
    with pytest.raises(BusinessError):
        normalize_image_quality("ultra")


def test_gpt_image_edit_does_not_forward_internal_disable_retry(monkeypatch):
    captured: dict = {}

    def fake_post_multipart(_url, fields, _files, _config, _timeout):
        captured["fields"] = fields
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_multipart", fake_post_multipart)
    config = GenerationModelConfig(
        "openai",
        "OpenAI",
        "https://api.openai.com/v1",
        "api",
        "test-key",
        "bearer",
        120,
        "gpt-image-2",
        disable_retry=True,
    )

    generate_image(
        config,
        "编辑图片",
        "data:image/png;base64,aW1hZ2U=",
        "1k",
        "1:1",
    )

    assert "disable_retry" not in captured["fields"]


def test_gpt_image_edit_uses_repeated_image_field_for_multiple_images(monkeypatch):
    captured: dict = {}

    def fake_post_multipart(url, fields, files, config, timeout):
        captured["files"] = files
        return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="}]}

    monkeypatch.setattr(image_generation, "_post_multipart", fake_post_multipart)
    config = GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 120, "gpt-image-2")
    image_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="

    generate_image(config, "融合两张图", [image_data, image_data], "1k", "1:1")

    assert [file[0] for file in captured["files"]] == ["image", "image"]



def test_grok_imagine_image_quality_uses_images_generations(monkeypatch):
    captured: dict = {}

    def fake_post_json(url, body, headers, timeout):
        captured["url"] = url
        captured["body"] = body
        return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="}]}

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    config = GenerationModelConfig(
        "openai-4",
        "OpenAI",
        "https://cpa.shyfai.cn",
        "api",
        "test-key",
        "bearer",
        120,
        "grok-imagine-image-quality",
    )

    image = generate_image(config, "帮我生一张二次元图片", None, "1k", "1:1")

    assert image.mime_type == "image/png"
    assert captured["url"] == "https://cpa.shyfai.cn/v1/images/generations"
    assert captured["body"]["model"] == "grok-imagine-image-quality"
    assert "response_format" not in captured["body"]


def test_grok_imagine_image_quality_edit_uses_images_edits(monkeypatch):
    captured: dict = {}

    def fake_post_multipart(url, fields, files, config, timeout):
        captured["url"] = url
        captured["fields"] = fields
        return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="}]}

    monkeypatch.setattr(image_generation, "_post_multipart", fake_post_multipart)
    config = GenerationModelConfig(
        "openai-4",
        "OpenAI",
        "https://cpa.shyfai.cn",
        "api",
        "test-key",
        "bearer",
        120,
        "grok-imagine-image-quality",
    )

    image = generate_image(
        config,
        "改成二次元风格",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
        "1k",
        "1:1",
    )

    assert image.mime_type == "image/png"
    assert captured["url"] == "https://cpa.shyfai.cn/v1/images/edits"
    assert captured["fields"]["model"] == "grok-imagine-image-quality"


@pytest.mark.parametrize("vendor_model", ["agent5-nano-banana-pro", "agent5-nano-banana2"])
def test_agent5_nano_banana_uses_images_generations_with_portrait_size(monkeypatch, vendor_model):
    captured: dict = {}

    def fake_post_json(url, body, headers, timeout):
        captured["url"] = url
        captured["body"] = body
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    config = GenerationModelConfig(
        "agent5",
        "Agent 5",
        "https://agent.shyfai.com/v1",
        "api",
        "test-key",
        "bearer",
        120,
        vendor_model,
    )

    generate_image(config, "生成竖版 Banner", None, "2k", "9:16")

    assert captured["url"] == "https://agent.shyfai.com/v1/images/generations"
    assert captured["body"]["model"] == vendor_model
    assert captured["body"]["prompt"] == "生成竖版 Banner"
    assert captured["body"]["size"] == "1152x2048"
    assert set(captured["body"]) == {"model", "prompt", "size", "quality"}


@pytest.mark.parametrize("vendor_model", ["agent5-nano-banana-pro", "agent5-nano-banana2"])
def test_agent5_nano_banana_uses_images_edits_with_portrait_size(monkeypatch, vendor_model):
    captured: dict = {}

    def fake_post_multipart(url, fields, files, config, timeout):
        captured["url"] = url
        captured["fields"] = fields
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_multipart", fake_post_multipart)
    config = GenerationModelConfig(
        "agent5",
        "Agent 5",
        "https://agent.shyfai.com/v1",
        "api",
        "test-key",
        "bearer",
        120,
        vendor_model,
    )

    generate_image(
        config,
        "基于原图生成竖版 Banner",
        "data:image/png;base64,aW1hZ2U=",
        "2k",
        "9:16",
    )

    assert captured["url"] == "https://agent.shyfai.com/v1/images/edits"
    assert captured["fields"]["model"] == vendor_model
    assert captured["fields"]["prompt"] == "基于原图生成竖版 Banner"
    assert captured["fields"]["size"] == "1152x2048"
    assert set(captured["fields"]) == {"model", "prompt", "size", "quality"}


def test_adobe_image_request_keeps_prompt_raw_and_forwards_upstream_fields(monkeypatch):
    captured: dict = {}

    def fake_post_json(_url, body, _headers, _timeout):
        captured["body"] = body
        return {"data": [{"b64_json": "aW1hZ2U="}]}

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    config = GenerationModelConfig(
        "adobe",
        "Adobe",
        "https://adobe.example/v1",
        "api",
        "test-key",
        "bearer",
        120,
        "agent5-gpt-image",
    )

    generate_image(
        config,
        "给我生成一张二次元图片",
        None,
        "4k",
        "16:9",
        quality="high",
        client_reference="IMG-4K-16X9",
    )

    assert captured["body"] == {
        "model": "agent5-gpt-image",
        "prompt": "给我生成一张二次元图片",
        "size": "3840x2160",
        "quality": "high",
        "client_reference": "IMG-4K-16X9",
    }


@pytest.mark.parametrize(
    ("resolution", "aspect_ratio", "expected_size"),
    [
        ("1k", "4:3", "1152x864"),
        ("1k", "3:4", "864x1152"),
        ("2k", "3:2", "2016x1344"),
        ("2k", "2:3", "1344x2016"),
        ("2k", "21:9", "2016x864"),
        ("4k", "21:9", "3696x1584"),
    ],
)
def test_openai_size_preserves_public_aspect_ratio(resolution, aspect_ratio, expected_size):
    size = _openai_size(resolution, aspect_ratio)
    assert size == expected_size
    width, height = (int(item) for item in size.split("x"))
    numerator, denominator = (int(item) for item in aspect_ratio.split(":"))
    assert Fraction(width, height) == Fraction(numerator, denominator)


def test_openai_4k_size_does_not_exceed_provider_limit():
    for aspect_ratio in ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"]:
        width, height = (int(item) for item in _openai_size("4k", aspect_ratio).split("x"))
        assert max(width, height) <= 3840

    assert _openai_size("4k", "3:4") == "2880x3840"


def test_provider_error_exposes_upstream_message():
    message, code, status_code = _provider_error_message(
        400,
        '{"error":{"message":"Your request was rejected by the safety system.","type":"image_generation_user_error","code":"content_policy_violation","safety_violations":["sexual"]}}',
    )

    assert message == "Your request was rejected by the safety system."
    assert status_code == 400
    assert code == 50212


def test_provider_timeout_error_is_normalized():
    message, code, status_code = _provider_error_message(
        400,
        '{"error":{"message":"已超时","type":"invalid_request_error","param":null,"code":"timeout"}}',
    )

    assert message == MODEL_TIMEOUT_MESSAGE
    assert code == MODEL_TIMEOUT_CODE
    assert status_code == 400


def test_provider_image_quota_error_is_normalized_without_vendor_copy():
    message, code, status_code = _provider_error_message(
        400,
        '{"error":{"message":"no available image quota","code":"no_available_image_quota"}}',
    )

    assert message == MODEL_IMAGE_CAPACITY_MESSAGE
    assert "quota" not in message.lower()
    assert code == 50230
    assert status_code == 503


def test_image_task_retries_timeout_once_and_passthrough_others():
    timeout_exc = BusinessError(MODEL_TIMEOUT_MESSAGE, code=MODEL_TIMEOUT_CODE, status_code=400)
    policy_exc = BusinessError("非常抱歉，生成的图片可能违反了防护限制", code=50212, status_code=400)

    assert catalog.IMAGE_TIMEOUT_MAX_ATTEMPTS == 2
    assert catalog.is_retryable_model_error(timeout_exc)
    assert not catalog.is_retryable_model_error(policy_exc)
    assert catalog.image_task_retry_message(timeout_exc, 1, 2) == "上游超时，已重新排队重试（1/2）"
    # 重试 1 次仍超时：只提示已超时
    assert catalog.image_task_failure_message(timeout_exc, 2) == MODEL_TIMEOUT_MESSAGE
    assert catalog.image_task_failure_message(policy_exc, 2) == "非常抱歉，生成的图片可能违反了防护限制"
    assert catalog.image_task_max_attempts(False) == 2
    assert catalog.image_task_max_attempts(True) == 1


def test_model_timeout_deadline_is_fixed_and_retries_only_receive_remaining_budget():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    deadline = catalog.task_deadline_at(now, 1200)
    config = GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 1200, "gpt-image-2")

    retry_config = catalog.task_attempt_generation_config(config, deadline, now=now.replace(second=30))

    assert deadline == now + timedelta(seconds=1200)
    assert retry_config.timeout_seconds == 1170
    with pytest.raises(BusinessError) as exc:
        catalog.task_attempt_generation_config(config, deadline, now=deadline)
    assert exc.value.code == MODEL_TIMEOUT_CODE


def test_generate_image_uses_model_timeout_without_image_specific_ceiling(monkeypatch):
    captured: dict = {}

    def fake_post_json(_url, _body, _headers, timeout):
        captured["timeout"] = timeout
        return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="}]}

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    config = GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 1200, "gpt-image-2")

    generate_image(config, "测试模型超时", None, "1k", "1:1")

    assert 600 < captured["timeout"] <= 1200


def test_result_download_uses_independent_budget_after_model_completed(monkeypatch):
    events: list[str] = []
    captured: dict = {}

    def fake_post_json(_url, _body, _headers, timeout):
        events.append("model_request")
        captured["model_timeout"] = timeout
        return {"data": [{"url": "https://files.example.test/result.png"}]}

    def fake_download(_url, timeout, request_headers=None):
        _ = request_headers
        events.append("download")
        captured["download_timeout"] = timeout
        return image_generation.GeneratedImage(content=b"image", mime_type="image/png")

    def on_model_completed(_trace):
        events.append("model_completed")

    def on_model_started():
        events.append("model_started")

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    monkeypatch.setattr(image_generation, "_download_image", fake_download)
    config = GenerationModelConfig(
        "openai",
        "OpenAI",
        "https://api.openai.com/v1",
        "api",
        "test-key",
        "bearer",
        100,
        "gpt-image-2",
    )

    generate_image(
        config,
        "测试阶段拆分",
        None,
        "1k",
        "1:1",
        on_model_started=on_model_started,
        on_model_completed=on_model_completed,
    )

    assert events == ["model_started", "model_request", "model_completed", "download"]
    assert 0 < captured["model_timeout"] <= 100
    assert captured["download_timeout"] == image_generation.settings.image_result_download_timeout_seconds
    assert captured["download_timeout"] > captured["model_timeout"]


def test_result_download_timeout_is_not_retryable_model_timeout():
    exc = BusinessError(
        RESULT_DOWNLOAD_TIMEOUT_MESSAGE,
        code=RESULT_DOWNLOAD_TIMEOUT_CODE,
        status_code=504,
    )

    assert not catalog.is_retryable_model_error(exc)
    assert catalog.image_task_failure_message(exc, 2) == RESULT_DOWNLOAD_TIMEOUT_MESSAGE


def test_result_download_reads_in_bounded_chunks(monkeypatch):
    read_sizes: list[int] = []
    payload = b"x" * (image_generation.DOWNLOAD_CHUNK_BYTES + 7)

    class FakeResponse:
        headers = {
            "Content-Type": "image/png",
            "Content-Length": str(len(payload)),
        }

        def __enter__(self):
            self.offset = 0
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            read_sizes.append(size)
            chunk = payload[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    monkeypatch.setattr(
        image_generation.urllib.request,
        "urlopen",
        lambda _request, timeout: FakeResponse(),
    )

    image = image_generation._download_image("https://files.example.test/result.png", timeout=60)

    assert image.content == payload
    assert read_sizes
    assert set(read_sizes) == {image_generation.DOWNLOAD_CHUNK_BYTES}


def test_input_image_download_retries_tls_handshake_timeout_and_recovers(monkeypatch):
    attempts = 0

    class FakeResponse:
        headers = {
            "Content-Type": "image/png",
            "Content-Length": "5",
        }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            if getattr(self, "read_done", False):
                return b""
            self.read_done = True
            return b"image"

    def fake_urlopen(_request, timeout):
        nonlocal attempts
        attempts += 1
        assert 0 < timeout <= image_generation.settings.image_result_download_read_timeout_seconds
        if attempts == 1:
            raise image_generation.urllib.error.URLError(
                TimeoutError("The handshake operation timed out")
            )
        return FakeResponse()

    monkeypatch.setattr(image_generation.settings, "image_download_retry_attempts", 3)
    monkeypatch.setattr(image_generation.settings, "image_download_retry_delay_seconds", 0)
    monkeypatch.setattr(image_generation.urllib.request, "urlopen", fake_urlopen)

    image = _input_image_from_value("https://files.example.test/input.png", timeout=60)

    assert image is not None
    assert image.content == b"image"
    assert attempts == 2


def test_input_image_download_falls_back_to_minio_after_cdn_retries(monkeypatch):
    urls: list[str] = []

    class FakeResponse:
        headers = {"Content-Type": "image/png", "Content-Length": "5"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            if getattr(self, "read_done", False):
                return b""
            self.read_done = True
            return b"image"

    def fake_urlopen(request, timeout):
        _ = timeout
        urls.append(request.full_url)
        if request.full_url.startswith("https://openagent-cdn.example/"):
            raise image_generation.urllib.error.URLError(
                TimeoutError("The handshake operation timed out")
            )
        return FakeResponse()

    monkeypatch.setattr(image_generation.settings, "qiniu_cdn_base_url", "https://openagent-cdn.example")
    monkeypatch.setattr(image_generation.settings, "minio_public_endpoint", "https://magic.shagentai.com")
    monkeypatch.setattr(image_generation.settings, "image_download_retry_attempts", 2)
    monkeypatch.setattr(image_generation.settings, "image_download_retry_delay_seconds", 0)
    monkeypatch.setattr(image_generation.urllib.request, "urlopen", fake_urlopen)

    image = _input_image_from_value(
        "https://openagent-cdn.example/image2-assets/images/input.png",
        timeout=60,
    )

    assert image.content == b"image"
    assert urls == [
        "https://openagent-cdn.example/image2-assets/images/input.png",
        "https://openagent-cdn.example/image2-assets/images/input.png",
        "http://minio:9000/image2-assets/images/input.png",
    ]


def test_input_image_download_timeout_reports_input_stage_after_retries(monkeypatch):
    attempts = 0

    def fake_urlopen(_request, timeout):
        _ = timeout
        nonlocal attempts
        attempts += 1
        raise image_generation.urllib.error.URLError(
            TimeoutError("The handshake operation timed out")
        )

    monkeypatch.setattr(image_generation.settings, "image_download_retry_attempts", 2)
    monkeypatch.setattr(image_generation.settings, "image_download_retry_delay_seconds", 0)
    monkeypatch.setattr(image_generation.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(BusinessError) as exc_info:
        _input_image_from_value("https://files.example.test/input.png", timeout=60)

    assert attempts == 2
    assert exc_info.value.code == image_generation.INPUT_DOWNLOAD_TIMEOUT_CODE
    assert exc_info.value.message == image_generation.INPUT_DOWNLOAD_TIMEOUT_MESSAGE


def test_result_download_retries_broken_pipe_without_reinvoking_model(monkeypatch):
    model_calls = 0
    download_attempts = 0

    class FakeResponse:
        headers = {
            "Content-Type": "image/png",
            "Content-Length": "5",
        }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            if getattr(self, "read_done", False):
                return b""
            self.read_done = True
            return b"image"

    def fake_post_json(_url, _body, _headers, _timeout):
        nonlocal model_calls
        model_calls += 1
        return {"data": [{"url": "https://files.example.test/result.png"}]}

    def fake_urlopen(_request, timeout):
        _ = timeout
        nonlocal download_attempts
        download_attempts += 1
        if download_attempts == 1:
            raise BrokenPipeError(image_generation.errno.EPIPE, "Broken pipe")
        return FakeResponse()

    monkeypatch.setattr(image_generation.settings, "image_download_retry_attempts", 3)
    monkeypatch.setattr(image_generation.settings, "image_download_retry_delay_seconds", 0)
    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    monkeypatch.setattr(image_generation.urllib.request, "urlopen", fake_urlopen)
    config = GenerationModelConfig(
        "openai",
        "OpenAI",
        "https://api.openai.com/v1",
        "api",
        "test-key",
        "bearer",
        100,
        "gpt-image-2",
    )

    image = generate_image(config, "测试结果下载重试", None, "1k", "1:1")

    assert image.content == b"image"
    assert model_calls == 1
    assert download_attempts == 2


def test_result_download_does_not_retry_non_transient_http_error(monkeypatch):
    attempts = 0

    def fake_urlopen(request, timeout):
        _ = timeout
        nonlocal attempts
        attempts += 1
        raise image_generation.urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(image_generation.settings, "image_download_retry_attempts", 3)
    monkeypatch.setattr(image_generation.settings, "image_download_retry_delay_seconds", 0)
    monkeypatch.setattr(image_generation.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(BusinessError) as exc_info:
        image_generation._download_image(
            "https://files.example.test/missing.png",
            timeout=60,
        )

    assert attempts == 1
    assert exc_info.value.code == image_generation.RESULT_DOWNLOAD_FAILED_CODE


def test_result_download_has_no_independent_global_concurrency_gate(monkeypatch):
    download_barrier = threading.Barrier(2, timeout=1)

    class FakeResponse:
        headers = {
            "Content-Type": "image/png",
            "Content-Length": "5",
        }

        def __enter__(self):
            download_barrier.wait()
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            if getattr(self, "read_done", False):
                return b""
            self.read_done = True
            return b"image"

    monkeypatch.setattr(
        image_generation.urllib.request,
        "urlopen",
        lambda _request, timeout: FakeResponse(),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda index: image_generation._download_image(
                    f"https://files.example.test/result-{index}.png",
                    timeout=5,
                ),
                range(2),
            )
        )

    assert [result.content for result in results] == [b"image", b"image"]


def test_generate_video_uses_model_timeout_without_video_specific_ceiling(monkeypatch):
    captured: dict = {}

    def fake_post_json(_url, _body, _headers, timeout):
        captured["post_timeout"] = timeout
        return {"video_url": "https://example.test/video.mp4"}

    def fake_download(_url, timeout, request_headers=None):
        _ = request_headers
        captured["download_timeout"] = timeout
        return image_generation.GeneratedImage(content=b"video", mime_type="video/mp4", source_url="https://example.test/video.mp4")

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    monkeypatch.setattr(image_generation, "_download_video", fake_download)
    config = GenerationModelConfig("xai", "xAI", "https://api.x.ai", "api", "test-key", "bearer", 1200, "grok-imagine-video")

    image_generation.generate_video(config, "测试模型超时", resolution="720p", duration="6s")

    assert 900 < captured["post_timeout"] <= 1200
    assert 0 < captured["download_timeout"] <= captured["post_timeout"]


def test_text_generation_uses_model_timeout_without_text_specific_ceiling(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(_request, timeout):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(text_generation.urllib.request, "urlopen", fake_urlopen)
    config = GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 1200, "gpt-4.1")

    assert text_generation._chat_completion(config, system="test", user="test") == "ok"
    assert captured["timeout"] == 1200


def test_stream_optimized_prompt_emits_each_delta_and_completion(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"clean "}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":"prompt"}}]}\n\n'
            yield b"data: [DONE]\n\n"

    monkeypatch.setattr(text_generation.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    config = GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 120, "gpt-4.1")

    events = list(text_generation.stream_optimized_prompt(config, "优化一张产品图"))

    assert events == [
        {"type": "status", "message": "正在连接优化模型…"},
        {"type": "delta", "text": "clean "},
        {"type": "delta", "text": "prompt"},
        {"type": "complete", "prompt": "clean prompt"},
    ]


@pytest.mark.parametrize(
    "response",
    [
        "你当前使用的是临时聊天，无法直接调用图片生成功能。",
        "This temporary chat cannot directly call image generation.",
    ],
)
def test_prompt_optimization_rejects_non_prompt_provider_response(response):
    with pytest.raises(BusinessError, match="优化模型未返回可用提示词"):
        text_generation._optimized_prompt_or_error(response)


@pytest.mark.asyncio
async def test_execute_image_task_batch_dispatches_once(monkeypatch):
    calls: list[object] = []
    wakes = 0

    async def fake_dispatch(*, batch_size=None):
        calls.append(batch_size)
        return 1

    def fake_wake():
        nonlocal wakes
        wakes += 1

    monkeypatch.setattr(catalog, "dispatch_image_tasks_once", fake_dispatch)
    monkeypatch.setattr(catalog, "wake_image_task_dispatcher", fake_wake)

    await catalog.execute_image_task_batch(
        [
            {"task_id": 1},
            {"task_id": 2},
            {"task_id": 3},
        ]
    )

    # 批量提交不再按 len 一次 claim，改走默认限流调度 + 唤醒 dispatcher
    assert calls == [None]
    assert wakes == 1


@pytest.mark.asyncio
async def test_dispatcher_loop_wakes_on_event(monkeypatch):
    calls = 0

    async def fake_dispatch():
        nonlocal calls
        calls += 1
        if calls == 1:
            return 0
        raise asyncio.CancelledError

    monkeypatch.setattr(catalog.settings, "image_task_dispatcher_interval_seconds", 60)
    monkeypatch.setattr(catalog, "dispatch_image_tasks_once", fake_dispatch)
    catalog.wake_image_task_dispatcher()

    with pytest.raises(asyncio.CancelledError):
        await catalog.image_task_dispatcher_loop()

    assert calls == 2


@pytest.mark.asyncio
async def test_user_image_concurrency_limit_defaults_to_one():
    class FakeDb:
        async def scalar(self, _query):
            return None

    assert await catalog.user_image_concurrency_limit(FakeDb(), 999) == 1


def test_image_task_reaper_scans_every_ten_minutes_by_default():
    assert catalog.settings.image_task_reaper_interval_seconds == 600


def test_global_image_generation_concurrency_is_not_forced_to_eight():
    repo_root = Path(__file__).resolve().parents[2]
    assert "IMAGE_GENERATION_MAX_CONCURRENCY" not in (repo_root / "docker-compose.yml").read_text()
    assert "IMAGE_GENERATION_MAX_CONCURRENCY=8" not in (repo_root / ".env.docker.example").read_text()


@pytest.mark.asyncio
async def test_image_generation_uses_dedicated_executor(monkeypatch):
    calls: list[object] = []

    class FakeLoop:
        async def run_in_executor(self, executor, fn, *args):
            calls.append(executor)
            return fn(*args)

    def fake_generate(*_args, **_kwargs):
        return "generated"

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(catalog, "generate_image", fake_generate)

    result, timing = await catalog.run_image_generation_in_executor(
        GenerationModelConfig("openai", "OpenAI", "https://api.openai.com/v1", "api", "test-key", "bearer", 120, "gpt-image-2"),
        "prompt",
        None,
        "1k",
        "1:1",
    )

    assert result == "generated"
    assert isinstance(timing, dict)
    assert "slot_wait_secs" in timing and "executor_wait_secs" in timing and "generate_secs" in timing
    assert calls == [catalog.image_generation_executor]


@pytest.mark.asyncio
async def test_generated_image_storage_uses_dedicated_executor(monkeypatch):
    calls: list[object] = []

    class FakeLoop:
        async def run_in_executor(self, executor, fn, *args):
            calls.append(executor)
            return fn(*args)

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(
        catalog,
        "store_generated_image_object",
        lambda **_kwargs: {"url": "http://example.test/image.png"},
    )

    result = await catalog.run_generated_image_storage_in_executor(
        user_id=1,
        content=b"image",
        mime_type="image/png",
    )

    assert result["url"] == "http://example.test/image.png"
    assert calls == [catalog.image_storage_executor]


@pytest.mark.asyncio
async def test_wait_for_model_execution_turn_only_promotes_queued_task(monkeypatch):
    class FakeResult:
        def first(self):
            return SimpleNamespace(id=2, created_at=datetime.now(UTC), status="queued")

    class FakeDb:
        async def execute(self, _query):
            return FakeResult()

        async def scalar(self, _query):
            return 0

    promoted: dict[str, object] = {}

    async def fake_model_limit(_db, _model_id):
        return 0

    async def fake_user_limit(_db, _user_id):
        return 5

    async def fake_mark(_db, task_id, status, failure_message=None, *, expected_statuses=None):
        promoted.update({"task_id": task_id, "status": status, "expected_statuses": expected_statuses})
        return True

    async def fake_heartbeat(_db, _task_id, *, expected_statuses=("queued", "running")):
        assert expected_statuses == ("queued",)
        return True

    monkeypatch.setattr(catalog, "model_concurrency_limit", fake_model_limit)
    monkeypatch.setattr(catalog, "user_image_concurrency_limit", fake_user_limit)
    monkeypatch.setattr(catalog, "mark_image_task_status", fake_mark)
    monkeypatch.setattr(catalog, "mark_image_task_worker_heartbeat", fake_heartbeat)

    assert await catalog.wait_for_model_execution_turn(FakeDb(), task_id=2, user_id=7, model_id=9) is True
    assert promoted == {"task_id": 2, "status": "running", "expected_statuses": ("queued",)}


@pytest.mark.asyncio
async def test_wait_for_model_execution_turn_does_not_revive_failed_task(monkeypatch):
    class FakeResult:
        def first(self):
            return SimpleNamespace(id=2, created_at=datetime.now(UTC), status="failed")

    class FakeDb:
        async def execute(self, _query):
            return FakeResult()

    async def fake_model_limit(_db, _model_id):
        return 0

    async def fake_user_limit(_db, _user_id):
        return 5

    async def fail_if_marked(*_args, **_kwargs):
        raise AssertionError("failed tasks must not be promoted")

    async def fake_heartbeat(_db, _task_id, *, expected_statuses=("queued", "running")):
        return True

    monkeypatch.setattr(catalog, "model_concurrency_limit", fake_model_limit)
    monkeypatch.setattr(catalog, "user_image_concurrency_limit", fake_user_limit)
    monkeypatch.setattr(catalog, "mark_image_task_status", fail_if_marked)
    monkeypatch.setattr(catalog, "mark_image_task_worker_heartbeat", fake_heartbeat)

    assert await catalog.wait_for_model_execution_turn(FakeDb(), task_id=2, user_id=7, model_id=9) is False


def test_video_endpoint_candidates_include_v1_paths():
    endpoints = image_generation._video_endpoint_candidates("https://cpa.shyfai.cn")
    assert "https://cpa.shyfai.cn/v1/videos/generations" in endpoints
    assert "https://cpa.shyfai.cn/v1/videos" in endpoints
    assert endpoints[0] == "https://cpa.shyfai.cn/v1/videos/generations"

    with_v1 = image_generation._video_endpoint_candidates("https://cpa.shyfai.cn/v1")
    assert "https://cpa.shyfai.cn/v1/videos/generations" in with_v1
    assert "https://cpa.shyfai.cn/v1/v1/videos/generations" not in with_v1


def test_video_poll_url_candidates_for_cliproxy():
    urls = image_generation._video_poll_url_candidates(
        "https://cpa.shyfai.cn/v1/videos/generations",
        "b4f1673d-b3a5-9ab5-a5e0-49067dc0648b",
    )
    assert "https://cpa.shyfai.cn/v1/videos/b4f1673d-b3a5-9ab5-a5e0-49067dc0648b" in urls


def test_extract_media_url_from_xai_video_payload():
    payload = {
        "status": "done",
        "video": {
            "url": "https://vidgen.x.ai/xai-vidgen-bucket/demo.mp4",
            "duration": 6,
        },
        "progress": 100,
    }
    assert (
        image_generation._extract_media_url(payload)
        == "https://vidgen.x.ai/xai-vidgen-bucket/demo.mp4"
    )


def test_extract_media_url_prefers_gateway_content_url():
    payload = {
        "status": "completed",
        "url": "/generated/provider-video.mp4",
        "content_url": "https://gateway.example/v1/videos/video-123/content",
    }

    assert image_generation._extract_media_url(payload) == payload["content_url"]


def test_download_video_forwards_provider_authorization(monkeypatch):
    captured: dict[str, str | None] = {}

    class FakeHeaders:
        @staticmethod
        def get_content_type():
            return "video/mp4"

    class FakeResponse:
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b"video"

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = str(timeout)
        return FakeResponse()

    monkeypatch.setattr(image_generation.urllib.request, "urlopen", fake_urlopen)
    result = image_generation._download_video(
        "https://newapi.example/v1/videos/video-123/content",
        30,
        request_headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
    )

    assert captured["authorization"] == "Bearer test-key"
    assert result.content == b"video"


def test_adobe_video_request_uses_newapi_reference_contract():
    config = GenerationModelConfig(
        "newapi",
        "NewAPI",
        "https://newapi.example/v1",
        "api",
        "test-key",
        "bearer",
        180,
        "agent5-veo31-ref",
    )
    refs = [
        image_generation.GeneratedImage(
            content=b"",
            mime_type="image/png",
            source_url=f"https://cdn.example/{name}.png",
        )
        for name in ("a", "b", "c")
    ]

    single = image_generation._video_request_bodies(
        config,
        "animate",
        "720p",
        "6",
        refs[:1],
        aspect_ratio="16:9",
    )
    multiple = image_generation._video_request_bodies(
        config,
        "animate",
        "1080p",
        "6",
        refs,
        aspect_ratio="9:16",
    )

    assert single[0]["image"] == "https://cdn.example/a.png"
    assert multiple[0]["images"] == [
        "https://cdn.example/a.png",
        "https://cdn.example/b.png",
        "https://cdn.example/c.png",
    ]
    assert "reference_images" not in multiple[0]


def test_generate_video_uses_newapi_content_route_for_adobe_result(monkeypatch):
    downloaded: list[str] = []
    download_headers: list[dict[str, str]] = []

    monkeypatch.setattr(
        image_generation,
        "_post_json",
        lambda *_args, **_kwargs: {"id": "video-123", "status": "queued"},
    )
    monkeypatch.setattr(
        image_generation,
        "_poll_video_job",
        lambda *_args, **_kwargs: {
            "id": "video-123",
            "status": "completed",
            "url": "/generated/provider-video.mp4",
        },
    )

    def fake_download(url, _timeout, request_headers=None):
        downloaded.append(url)
        download_headers.append(request_headers or {})
        return image_generation.GeneratedImage(
            content=b"video",
            mime_type="video/mp4",
            source_url=url,
        )

    monkeypatch.setattr(image_generation, "_download_video", fake_download)
    config = GenerationModelConfig(
        "newapi",
        "NewAPI",
        "https://newapi.example/v1",
        "api",
        "test-key",
        "bearer",
        180,
        "agent5-sora2",
    )

    result = image_generation.generate_video(
        config,
        "test",
        resolution="720p",
        duration="8",
        aspect_ratio="16:9",
    )

    assert downloaded == ["https://newapi.example/v1/videos/video-123/content"]
    assert download_headers[0]["Authorization"] == "Bearer test-key"
    assert result.source_url == downloaded[0]


def test_generate_video_polls_request_id_and_returns_source_url(monkeypatch):
    posts: list[str] = []
    polls: list[str] = []

    def fake_post(url, body, headers, timeout):
        posts.append(url)
        assert body["model"] == "grok-imagine-video-1.5-preview"
        return {"request_id": "vid-123"}

    def fake_poll(poll_url, headers, timeout, **_kwargs):
        polls.append(poll_url)
        return {
            "status": "done",
            "video": {"url": "https://vidgen.x.ai/demo.mp4", "duration": 6},
            "progress": 100,
        }

    def fake_download(url, timeout, request_headers=None):
        _ = request_headers
        return image_generation.GeneratedImage(
            content=b"\x00\x00",
            mime_type="video/mp4",
            source_url=url,
        )

    monkeypatch.setattr(image_generation, "_post_json", fake_post)
    monkeypatch.setattr(image_generation, "_poll_video_job", fake_poll)
    monkeypatch.setattr(image_generation, "_download_video", fake_download)

    config = GenerationModelConfig(
        provider_code="openai-6",
        provider_name="openai",
        base_url="https://cpa.shyfai.cn",
        access_mode="api",
        api_key="test-key",
        auth_type="bearer",
        timeout_seconds=180,
        vendor_model="grok-imagine-video-1.5-preview",
    )
    result = image_generation.generate_video(config, "cool transition", resolution="720p", duration="6s")
    assert result.source_url == "https://vidgen.x.ai/demo.mp4"
    assert posts[0] == "https://cpa.shyfai.cn/v1/videos/generations"
    assert any(url.endswith("/v1/videos/vid-123") for url in polls)



def test_video_request_bodies_official_first_and_duration_only():
    config = GenerationModelConfig(
        provider_code="xai",
        provider_name="xAI",
        base_url="https://api.x.ai",
        access_mode="api",
        api_key="k",
        auth_type="bearer",
        timeout_seconds=180,
        vendor_model="grok-imagine-video",
    )
    bodies = image_generation._video_request_bodies(
        config,
        "a prompt",
        "720p",
        "8s",
        [],
        aspect_ratio="16:9",
        user="42",
    )
    assert bodies, "expected at least one body"
    first = bodies[0]
    assert first["model"] == "grok-imagine-video"
    assert first["prompt"] == "a prompt"
    assert first["duration"] == 8
    assert first["resolution"] == "720p"
    assert first["aspect_ratio"] == "16:9"
    assert first["user"] == "42"
    assert "seconds" not in first
    assert "size" not in first
    assert "mode" not in first
    # fallback may use seconds but never both
    for body in bodies:
        assert not ("duration" in body and "seconds" in body)


def test_video_request_bodies_multi_image_b_scheme():
    config = GenerationModelConfig(
        provider_code="xai",
        provider_name="xAI",
        base_url="https://api.x.ai",
        access_mode="api",
        api_key="k",
        auth_type="bearer",
        timeout_seconds=180,
        vendor_model="grok-imagine-video",
    )
    images = [
        image_generation.GeneratedImage(content=b"a", mime_type="image/png", source_url="https://cdn.example/a.png"),
        image_generation.GeneratedImage(content=b"b", mime_type="image/png", source_url="https://cdn.example/b.png"),
        image_generation.GeneratedImage(content=b"c", mime_type="image/png", source_url="https://cdn.example/c.png"),
    ]
    bodies = image_generation._video_request_bodies(
        config,
        "animate",
        "1080p",
        "6",
        images,
        aspect_ratio="9:16",
    )
    first = bodies[0]
    assert first["image"] == {"url": "https://cdn.example/a.png"}
    assert first["reference_images"] == [
        {"url": "https://cdn.example/b.png"},
        {"url": "https://cdn.example/c.png"},
    ]
    assert first["duration"] == 6
    assert first["resolution"] == "1080p"


def test_normalize_video_duration_rejects_out_of_range():
    import pytest
    from app.core.exceptions import BusinessError

    with pytest.raises(BusinessError):
        image_generation._normalize_video_duration_seconds("20s")
    with pytest.raises(BusinessError):
        image_generation._normalize_video_duration_seconds("0")
    assert image_generation._normalize_video_duration_seconds("15s") == 15


def test_poll_video_job_treats_expired_as_failure(monkeypatch):
    import io
    import pytest
    from app.core.exceptions import BusinessError

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"status":"expired","error":{"message":"job expired"}}'

    monkeypatch.setattr(image_generation.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    with pytest.raises(BusinessError) as exc:
        image_generation._poll_video_job("https://example/v1/videos/x", {}, 30)
    assert "过期" in str(exc.value.message) or "expired" in str(exc.value.message).lower() or "过期" in str(exc.value)
