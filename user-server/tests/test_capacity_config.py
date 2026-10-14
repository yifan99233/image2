import pytest
from pydantic import ValidationError

from app.core.config import Settings


CAPACITY_ENV_KEYS = (
    "DATABASE_POOL_SIZE",
    "USER_DATABASE_POOL_SIZE",
    "DATABASE_MAX_OVERFLOW",
    "USER_DATABASE_MAX_OVERFLOW",
    "IMAGE_TASK_GENERATION_THREAD_POOL_SIZE",
    "USER_IMAGE_TASK_GENERATION_THREAD_POOL_SIZE",
    "IMAGE_TASK_STORAGE_THREAD_POOL_SIZE",
    "USER_IMAGE_TASK_STORAGE_THREAD_POOL_SIZE",
    "IMAGE_TASK_GENERATION_MAX_INFLIGHT",
    "USER_IMAGE_TASK_GENERATION_MAX_INFLIGHT",
    "IMAGE_TASK_DISPATCHER_BATCH_SIZE",
    "USER_IMAGE_TASK_DISPATCHER_BATCH_SIZE",
    "IMAGE_TASK_DISPATCHER_MAX_INFLIGHT",
    "USER_IMAGE_TASK_DISPATCHER_MAX_INFLIGHT",
)


def test_default_runtime_capacity_is_bounded_per_worker(monkeypatch) -> None:
    for key in CAPACITY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://image2:test@postgres:5432/image2",
    )

    settings = Settings(_env_file=None)

    assert settings.image_task_generation_thread_pool_size == 64
    assert settings.image_task_storage_thread_pool_size == 64
    assert settings.image_task_generation_max_inflight == 64
    assert settings.image_task_dispatcher_batch_size == 64
    assert settings.image_task_dispatcher_max_inflight == 64
    assert settings.image_task_queue_limit_per_user == 2000
    assert settings.database_pool_size == 40
    assert settings.database_max_overflow == 40


def test_runtime_capacity_rejects_a_hidden_lower_layer(monkeypatch) -> None:
    for key in CAPACITY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://image2:test@postgres:5432/image2",
    )
    monkeypatch.setenv("USER_IMAGE_TASK_GENERATION_MAX_INFLIGHT", "512")
    monkeypatch.setenv("USER_IMAGE_TASK_GENERATION_THREAD_POOL_SIZE", "64")

    with pytest.raises(
        ValidationError,
        match="image_task_generation_thread_pool_size=64",
    ):
        Settings(_env_file=None)
