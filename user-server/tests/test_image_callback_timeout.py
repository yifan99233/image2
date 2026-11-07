import asyncio
from datetime import UTC, datetime

import pytest

from app.api.routes import catalog
from app.services.image_generation import GeneratedImage, GenerationModelConfig


@pytest.mark.parametrize("callback", ["started", "completed"])
@pytest.mark.parametrize("budget,passes", [(0.01, False), (0.5, True)])
async def test_database_callback_uses_configured_wait_budget(monkeypatch, callback, budget, passes):
    async def started(*args):
        if callback == "started":
            await asyncio.sleep(0.05)
        return datetime.now(UTC)

    async def completed(*args):
        if callback == "completed":
            await asyncio.sleep(0.05)
        return True

    def generate(*args, **kwargs):
        kwargs["on_model_started"]()
        result = GeneratedImage(content=b"result", mime_type="image/png")
        kwargs["on_model_completed"](result)
        return result

    monkeypatch.setattr(catalog, "_persist_image_model_started", started)
    monkeypatch.setattr(catalog, "_persist_image_model_completed", completed)
    monkeypatch.setattr(catalog, "generate_image", generate)
    monkeypatch.setattr(catalog.settings, "image_task_callback_timeout_seconds", budget)
    config = GenerationModelConfig("probe", "probe", "https://unused.invalid", "api", "unused", "bearer", 300, "probe")
    operation = catalog.run_image_generation_in_executor(config, "probe", None, "1k", "1:1", task_id=1)
    if passes:
        result, timing = await operation
        assert result.content == b"result" and timing["model_completed"]
    else:
        with pytest.raises(TimeoutError):
            await operation
        # Timed-out DB callbacks are not cancelled or retried by this path.
        await asyncio.sleep(0.06)
