import base64
import json
from dataclasses import replace
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from PIL import Image
from sqlalchemy import select, text, update

from app.api.routes import catalog
from app.core.exceptions import BusinessError
from app.models.image_batch_upload import ImageBatchUpload
from app.models.user import User
from app.services import image_batch_uploads as uploads, image_generation as generation
from app.services.image_parameters import image_output_options, normalize_image_size
from test_batch_groups import sessions, payload as grouped_payload, create, counts
from test_batch_progress import batch_client


CONFIG = generation.GenerationModelConfig("test", "test", "https://upstream.invalid/v1", "api", "test-key", "bearer", 120, "gpt-image-2")
OPTIONS = {"size": "2048x3072", "output_format": "webp"}


@pytest.mark.parametrize("size", ["0x1024", "1025x1024", "256x256", "3840x3840", "3840x1024", "4096x2048", "oops", 1024])
def test_invalid_dimensions_fail(size):
    with pytest.raises(BusinessError):
        normalize_image_size(size)


def test_normalization_and_legacy_defaults():
    assert image_output_options({}) == {}
    assert image_output_options({"size": None, "output_format": None}) == {}
    assert image_output_options({"size": "2048×3072", "output_format": "JPG"}) == {"size": "2048x3072", "output_format": "jpeg"}
    assert normalize_image_size("auto") == "auto"
    with pytest.raises(BusinessError):
        image_output_options({"output_format": "gif"})


@pytest.mark.parametrize("editing", [False, True])
@pytest.mark.parametrize("fmt,mime", [("png", "image/png"), ("jpeg", "image/jpeg"), ("webp", "image/webp")])
def test_upstream_receives_exact_size_format_and_returns_correct_mime(monkeypatch, editing, fmt, mime):
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "red").save(buffer, format=fmt.upper())
    content = buffer.getvalue()
    calls = []
    monkeypatch.setattr(generation, "_input_images_from_values", lambda *_: [generation.GeneratedImage(content, mime)] if editing else [])
    def post(endpoint, fields, *_):
        calls.append((endpoint, fields))
        return {"data": [{"b64_json": base64.b64encode(content).decode()}]}
    monkeypatch.setattr(generation, "_post_json", post)
    monkeypatch.setattr(generation, "_post_multipart", post)
    result = generation.generate_image(CONFIG, "exact original prompt", resolution="1k", aspect_ratio="1:1", size="2048x3072", output_format=fmt)
    assert calls[0][0].endswith("/images/edits" if editing else "/images/generations")
    assert calls[0][1]["size"] == "2048x3072"
    assert calls[0][1]["output_format"] == fmt
    assert calls[0][1]["prompt"] == "exact original prompt"
    assert result.mime_type == mime and result.content == content


@pytest.mark.parametrize("config", [replace(CONFIG, access_mode="sdk"), replace(CONFIG, vendor_model="grok-imagine-image"), replace(CONFIG, provider_code="gemini")])
def test_unsupported_routes_reject_explicit_options(config):
    with pytest.raises(BusinessError):
        generation.validate_image_output_options(config, **OPTIONS)


async def prepare(sessions, work_type="image_edit"):
    async with sessions() as db:
        await db.execute(update(catalog.image_models_table).values(vendor_model="gpt-image-2", work_type=work_type))
        await db.execute(text("UPDATE image_model_prices SET work_type=:work_type"), {"work_type": work_type})
        await db.commit()


@pytest.mark.parametrize("work_type", ["image_edit", "text_to_image"])
async def test_single_submission_persistence_dispatch_and_history(sessions, work_type):
    await prepare(sessions, work_type)
    value = {"model_id": 5, "work_type": work_type, "prompt": "keep exact", "resolution": "1k", "aspect_ratio": "1:1", **OPTIONS}
    background = BackgroundTasks()
    async with sessions() as db:
        result = await catalog.create_image_task(value, background, await db.get(User, 1), db)
        assert all(result.data[key] == val for key, val in OPTIONS.items())
    assert all(background.tasks[0].args[0][0][key] == val for key, val in OPTIONS.items())
    async with sessions() as db:
        row = (await db.execute(select(catalog.image_tasks_table))).mappings().one()
        assert all(catalog.serialize_task(row)[key] == val for key, val in OPTIONS.items())
        claimed = await catalog.queued_image_task_payloads_for_dispatch(db, limit=10)
        assert len(claimed) == 1
        assert all(claimed[0][key] == val for key, val in OPTIONS.items())


async def test_grouped_batch_retains_options_and_hash_distinguishes_format(sessions):
    await prepare(sessions)
    value = {**grouped_payload(), **OPTIONS}
    result = await create(sessions, value)
    assert all(all(task[key] == val for key, val in OPTIONS.items()) for task in result.data["tasks"])
    with pytest.raises(BusinessError) as caught:
        await create(sessions, {**value, "output_format": "jpeg"})
    assert caught.value.status_code == 409
    async with sessions() as db:
        await db.execute(update(catalog.image_tasks_table).values(status="failed"))
        await db.commit()
        user = await db.get(User, 1)
        sources = await catalog.retry_source_tasks(db, user, value["batch_id"])
        _, token = await catalog.price_retry_sources(db, user, sources)
        _, changed_token = await catalog.price_retry_sources(db, user, [{**row, "output_format": "jpeg"} for row in sources])
        assert token != changed_token
        assert all(row["size"] == OPTIONS["size"] for row in sources)


async def test_uploaded_batch_materializes_options_and_legacy_hash_is_preserved(sessions, batch_client):
    await prepare(sessions, "text_to_image")
    manifest = {"version": 1, "work_type": "batch_generate", "model_id": 5, "batch_id": "batch-" + uuid4().hex,
                "resolution": "1k", "aspect_ratio": "1:1", "quality": "auto", "prompts": ["one", "two"], **OPTIONS}
    response = await batch_client.post("/image-tasks/batch-upload", files={"manifest": ("prompts.json", json.dumps(manifest), "application/json")})
    assert response.status_code == 202, response.text
    async with sessions() as db:
        job_id = await db.scalar(select(ImageBatchUpload.id))
    await uploads.process_upload(job_id, sessions)
    async with sessions() as db:
        rows = (await db.execute(select(catalog.image_tasks_table))).mappings().all()
        assert len(rows) == 2
        assert all(all(row[key] == val for key, val in OPTIONS.items()) for row in rows)
    normalized = uploads.parse_manifest(json.dumps(manifest).encode())
    assert uploads.manifest_hash(normalized) != uploads.manifest_hash({**normalized, "size": "1536x1024"})
    legacy = {key: value for key, value in normalized.items() if key not in OPTIONS}
    assert uploads.manifest_hash(legacy) == uploads.manifest_hash({**legacy, "size": None, "output_format": None})


async def test_invalid_options_rejected_before_billing(sessions):
    value = {**grouped_payload(), **OPTIONS}
    with pytest.raises(BusinessError, match="不支持自定义尺寸"):
        await create(sessions, value)
    assert await counts(sessions) == (0, 0, 2000, 20)


async def test_executor_forwards_output_options(monkeypatch):
    captured = {}
    def generate(*args, **kwargs):
        captured.update(kwargs)
        return generation.GeneratedImage(b"image", "image/webp")
    monkeypatch.setattr(catalog, "generate_image", generate)
    await catalog.run_image_generation_in_executor(CONFIG, "prompt", None, "1k", "1:1", **OPTIONS)
    assert all(captured[key] == value for key, value in OPTIONS.items())


async def test_model_list_reports_provider_route_capabilities(sessions, monkeypatch):
    from unittest.mock import AsyncMock
    await prepare(sessions)
    monkeypatch.setattr(catalog, "model_options", AsyncMock(return_value=([{"value": "1k", "label": "1K"}], [{"value": "1:1", "label": "1:1"}], [])))
    async with sessions() as db:
        user = await db.get(User, 1)
        result = await catalog.models("image_edit", user, db)
        assert result.data[0]["supports_custom_size"] and result.data[0]["supports_output_format"]
        await db.execute(update(catalog.image_model_providers_table).values(access_mode="sdk"))
        await db.commit()
        result = await catalog.models("image_edit", user, db)
        assert not result.data[0]["supports_custom_size"] and not result.data[0]["supports_output_format"]


async def test_in_place_retry_preserves_size_and_format(sessions, batch_client):
    from test_batch_retries import failed, preview, process, snapshot
    await prepare(sessions)
    await failed(sessions, statuses=["failed", "refunded"], **OPTIONS)
    request, _ = await preview(batch_client)
    response = await batch_client.post("/image-tasks/batches/retry", json=request)
    assert response.status_code == 200, response.text
    await process(sessions)
    rows, _, _ = await snapshot(sessions)
    assert len(rows) == 2
    assert all(row["status"] == "queued" and all(row[key] == value for key, value in OPTIONS.items()) for row in rows)


@pytest.mark.parametrize("model", ["gpt-image-2-adx2", "gpt-image-2.5-flare-adx2"])
@pytest.mark.parametrize("editing", [False, True])
def test_adx2_explicit_size_is_forwarded_without_changing_default_tier_contract(monkeypatch, model, editing):
    captured = {}
    monkeypatch.setattr(generation, "_input_images_from_values", lambda *_: [generation.GeneratedImage(b"ref", "image/png")] if editing else [])
    def post(endpoint, fields, *_):
        captured.update(fields)
        return {"data": [{"b64_json": base64.b64encode(b"image").decode()}]}
    monkeypatch.setattr(generation, "_post_json", post)
    monkeypatch.setattr(generation, "_post_multipart", post)
    generation.generate_image(replace(CONFIG, vendor_model=model), "prompt", resolution="2k", aspect_ratio="3:2", quality="high", **OPTIONS)
    assert captured["size"] == OPTIONS["size"]
    assert captured["output_format"] == "webp"
    assert captured["resolution"] == "2k" and captured["quality"] == "high"
