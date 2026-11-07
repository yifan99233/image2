from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.api.routes.catalog import (
    ImageTaskStatusesRequest,
    MAX_TASK_STATUS_BATCH_SIZE,
    USER_IMAGE_TASK_FAILURE_MESSAGE,
    is_retryable_model_error,
    is_retryable_model_rate_limit,
    resolve_input_image_urls,
    serialize_task,
)
from app.api.routes.catalog_serializers import serialize_gallery_work, serialize_user_work
from app.api.routes.site import normalize_system_announcement
from app.core.exceptions import BusinessError
from app.services.image_generation import MODEL_TIMEOUT_CODE, MODEL_TIMEOUT_MESSAGE
from app.services.image_thumbnails import (
    THUMBNAIL_EDGE_PX,
    create_webp_thumbnail,
    is_valid_thumbnail_token,
    thumbnail_path,
    thumbnail_token,
)


async def _auth_headers(client):
    response = await client.post(
        "/auth/register",
        json={"username": "catalog-user", "email": "catalog@example.com", "password": "strong-pass-123"},
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_image_tasks_list_returns_empty_list(client):
    headers = await _auth_headers(client)

    response = await client.get("/image-tasks", headers=headers)

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"] == []


async def test_resolve_input_image_urls_reuses_all_owned_urls_in_submitted_order():
    first_url = "https://cdn.example.test/images/result.png"
    second_url = "https://cdn.example.test/images/original.png"

    class FakeResult:
        def all(self):
            return [
                type("Row", (), {"url": second_url})(),
                type("Row", (), {"url": first_url})(),
            ]

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    urls = await resolve_input_image_urls(
        FakeSession(),
        site_id=2,
        user_id=32,
        payload={
            "input_image_ids": [0],
            "input_image_urls": [first_url, second_url, first_url],
        },
        max_input_images=4,
    )

    assert urls == [first_url, second_url]


async def test_resolve_input_image_urls_prefers_browser_cdn_over_local_mirror():
    cdn_url = "https://cdn.example.test/image2-assets/images/input.png"
    local_url = "https://magic.shagentai.com/image2-assets/images/input.png"

    class FakeResult:
        def all(self):
            return [type("Row", (), {"id": 11, "url": cdn_url, "local_url": local_url})()]

        def __iter__(self):
            return iter(self.all())

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    urls = await resolve_input_image_urls(
        FakeSession(),
        site_id=2,
        user_id=32,
        payload={"input_image_ids": [11]},
        max_input_images=4,
    )

    assert urls == [cdn_url]


async def test_resolve_input_image_urls_rejects_unowned_reused_url():
    owned_url = "https://cdn.example.test/images/result.png"
    unowned_url = "https://attacker.example.test/private.png"

    class FakeResult:
        def all(self):
            return [type("Row", (), {"url": owned_url})()]

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    with pytest.raises(BusinessError) as exc_info:
        await resolve_input_image_urls(
            FakeSession(),
            site_id=2,
            user_id=32,
            payload={
                "input_image_ids": [],
                "input_image_urls": [owned_url, unowned_url],
            },
            max_input_images=4,
        )

    assert exc_info.value.code == 40420


def test_image_task_status_batch_is_bounded():
    request = ImageTaskStatusesRequest(task_ids=list(range(1, MAX_TASK_STATUS_BATCH_SIZE + 1)))

    assert len(request.task_ids) == MAX_TASK_STATUS_BATCH_SIZE

    with pytest.raises(ValidationError):
        ImageTaskStatusesRequest(task_ids=list(range(1, MAX_TASK_STATUS_BATCH_SIZE + 2)))


def test_thumbnail_token_is_bound_to_task_and_source():
    source_url = "https://magic.shyfai.com/image2-assets/generated/7/example.png"
    token = thumbnail_token(7, source_url)

    assert is_valid_thumbnail_token(7, source_url, token)
    assert not is_valid_thumbnail_token(8, source_url, token)
    assert not is_valid_thumbnail_token(7, f"{source_url}?changed=1", token)
    assert thumbnail_path(7, source_url).endswith(f"?token={token}")


def test_thumbnail_conversion_is_bounded_webp():
    from io import BytesIO

    from PIL import Image

    original = BytesIO()
    Image.new("RGB", (1800, 1200), (42, 76, 110)).save(original, format="PNG")

    thumbnail = create_webp_thumbnail(original.getvalue())

    with Image.open(BytesIO(thumbnail)) as image:
        assert image.format == "WEBP"
        assert max(image.size) == THUMBNAIL_EDGE_PX
    assert len(thumbnail) < len(original.getvalue())


def test_successful_image_task_exposes_signed_thumbnail_url():
    source_url = "https://magic.shyfai.com/image2-assets/generated/7/example.png"
    task = serialize_task(
        {
            "id": 7,
            "task_no": "IMGTHUMB",
            "work_type": "text_to_image",
            "model_id": 5,
            "model_name": "IMAGE2",
            "prompt": "test",
            "resolution": "1k",
            "aspect_ratio": "1:1",
            "credit_cost": 14,
            "status": "succeeded",
            "failure_message": None,
            "input_image_url": None,
            "output_image_url": source_url,
            "is_collected": False,
            "created_at": datetime(2026, 7, 5, tzinfo=UTC),
            "finished_at": datetime(2026, 7, 5, tzinfo=UTC),
        }
    )

    output = task["output_images"][0]
    canonical_url = "https://magic.shyfai.cn/image2-assets/generated/7/example.png"
    assert output["url"] == canonical_url
    assert output["thumbnail_url"] == thumbnail_path(7, canonical_url)


def test_work_serializers_expose_the_task_aspect_ratio_for_gallery_layout():
    row = {
        "id": 8,
        "work_type": "text_to_image",
        "aspect_ratio": "9:16",
        "model_name": "gpt-image-2",
        "prompt": "portrait",
        "output_image_url": "https://cdn.example.test/portrait.png",
        "input_image_urls": "[]",
        "created_at": datetime(2026, 8, 5, tzinfo=UTC),
        "gallery_featured_at": datetime(2026, 8, 5, tzinfo=UTC),
        "user_id": 2,
    }

    gallery_work = serialize_gallery_work(row)
    user_work = serialize_user_work(row)

    assert gallery_work["aspect_ratio"] == "9:16"
    assert user_work["aspect_ratio"] == "9:16"


def test_only_timeout_errors_are_retryable():
    assert is_retryable_model_error(BusinessError(MODEL_TIMEOUT_MESSAGE, code=MODEL_TIMEOUT_CODE, status_code=400))
    assert is_retryable_model_error(BusinessError("已超时", code=50212, status_code=400))
    # 内容策略 / 限流 / 其它错误：不重试，透传 message
    assert not is_retryable_model_error(
        BusinessError("非常抱歉，生成的图片可能违反了防护限制", code=50212, status_code=400)
    )
    assert not is_retryable_model_error(BusinessError("模型调用失败：HTTP 429 {}", code=50229, status_code=429))
    assert not is_retryable_model_error(Exception("Concurrency limit exceeded for user, please retry later"))
    assert not is_retryable_model_error(BusinessError("模型未返回图片结果", code=50214, status_code=502))
    assert is_retryable_model_rate_limit is is_retryable_model_error


def test_serialize_failed_task_exposes_failure_message():
    task = serialize_task(
        {
            "id": 1,
            "task_no": "IMGTEST",
            "batch_id": "batch-test-001",
            "work_type": "image_edit",
            "model_id": 5,
            "model_name": "IMAGE2",
            "prompt": "test",
            "resolution": "1k",
            "aspect_ratio": "1:1",
            "credit_cost": 14,
            "status": "failed",
            "failure_message": "非常抱歉，生成的图片可能违反了防护限制",
            "input_image_url": None,
            "output_image_url": None,
            "is_collected": False,
            "created_at": datetime(2026, 7, 5, tzinfo=UTC),
            "finished_at": datetime(2026, 7, 5, tzinfo=UTC),
        }
    )

    assert task["failure_message"] == "非常抱歉，生成的图片可能违反了防护限制"
    assert task["quality"] == "auto"
    assert task["batch_id"] == "batch-test-001"

    empty = serialize_task(
        {
            "id": 2,
            "task_no": "IMGTEST2",
            "work_type": "text_to_image",
            "model_id": 5,
            "model_name": "IMAGE2",
            "prompt": "test",
            "resolution": "1k",
            "aspect_ratio": "1:1",
            "credit_cost": 14,
            "status": "failed",
            "failure_message": None,
            "input_image_url": None,
            "output_image_url": None,
            "is_collected": False,
            "created_at": datetime(2026, 7, 5, tzinfo=UTC),
            "finished_at": datetime(2026, 7, 5, tzinfo=UTC),
        }
    )
    assert empty["failure_message"] == USER_IMAGE_TASK_FAILURE_MESSAGE


def test_running_image_task_exposes_generation_and_download_stages():
    base_row = {
        "id": 3,
        "task_no": "IMGSTAGE",
        "work_type": "text_to_image",
        "model_id": 5,
        "model_name": "IMAGE2",
        "prompt": "test",
        "resolution": "1k",
        "aspect_ratio": "1:1",
        "credit_cost": 14,
        "status": "running",
        "failure_message": None,
        "input_image_url": None,
        "output_image_url": None,
        "is_collected": False,
        "created_at": datetime(2026, 7, 5, tzinfo=UTC),
        "finished_at": None,
    }

    generating = serialize_task({**base_row, "provider_http_status": None})
    downloading = serialize_task({**base_row, "provider_http_status": 200})

    assert generating["status"] == "running"
    assert generating["progress_stage"] == "generating"
    assert downloading["status"] == "running"
    assert downloading["progress_stage"] == "downloading"


def test_public_site_config_normalizes_system_announcement():
    assert normalize_system_announcement('{"is_enabled": true, "title": "  服务通知 ", "content": "  创作服务已恢复。  "}') == {
        "is_enabled": True,
        "title": "服务通知",
        "content": "创作服务已恢复。",
        "image_url": "",
    }
    assert normalize_system_announcement("not-json") == {"is_enabled": False, "title": "", "content": "", "image_url": ""}
