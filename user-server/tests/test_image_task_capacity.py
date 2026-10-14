"""Exercise 500 execution slots with local results; never call a paid provider."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
import resource
import threading
from time import perf_counter

from sqlalchemy import select

from app.api.routes import catalog
from app.services.image_generation import GeneratedImage, GenerationModelConfig
from test_batch_groups import sessions
from test_batch_progress import seed


async def test_500_simultaneous_results_persist_callbacks_and_finish_storage(sessions, monkeypatch):
    count = 500
    await seed(sessions, "capacity", ["running"] * count, worker_started_at=datetime.now(UTC))
    async with sessions() as db:
        ids = (await db.scalars(select(catalog.image_tasks_table.c.id))).all()
    generation_barrier = threading.Barrier(count, timeout=30)
    storage_barrier = threading.Barrier(count, timeout=30)
    lock = threading.Lock()
    active = {"generation": 0, "storage": 0}
    peaks = dict(active)

    def generate(*args, **kwargs):
        kwargs["on_model_started"]()
        with lock:
            active["generation"] += 1
            peaks["generation"] = max(peaks["generation"], active["generation"])
        generation_barrier.wait()
        image = GeneratedImage(content=b"x" * (2 * 1024 * 1024), mime_type="image/png", provider_http_status=200)
        kwargs["on_model_completed"](image)
        with lock:
            active["generation"] -= 1
        return image

    def store(**kwargs):
        assert len(kwargs["content"]) == 2 * 1024 * 1024
        with lock:
            active["storage"] += 1
            peaks["storage"] = max(peaks["storage"], active["storage"])
        storage_barrier.wait()
        with lock:
            active["storage"] -= 1
        return {"verified_bytes": len(kwargs["content"])}

    monkeypatch.setattr(catalog, "generate_image", generate)
    monkeypatch.setattr(catalog, "store_generated_image_object", store)
    monkeypatch.setattr(catalog, "image_generation_inflight", asyncio.Semaphore(count))
    config = GenerationModelConfig("local", "local", "https://unused.invalid", "api", "unused", "bearer", 225, "local")
    timings = []
    started = perf_counter()
    cpu_started = resource.getrusage(resource.RUSAGE_SELF)
    with ThreadPoolExecutor(max_workers=count) as generation, ThreadPoolExecutor(max_workers=count) as storage:
        monkeypatch.setattr(catalog, "image_generation_executor", generation)
        monkeypatch.setattr(catalog, "image_storage_executor", storage)
        async def execute(task_id):
            begin = perf_counter()
            image, timing = await catalog.run_image_generation_in_executor(config, "local", None, "1k", "1:1", task_id=task_id)
            stored = await catalog.run_generated_image_storage_in_executor(user_id=1, content=image.content, mime_type=image.mime_type)
            timings.append(perf_counter() - begin)
            return stored
        results = await asyncio.wait_for(asyncio.gather(*(execute(task_id) for task_id in ids)), timeout=60)
    assert len(results) == count and peaks == {"generation": count, "storage": count}
    async with sessions() as db:
        rows = (await db.execute(select(catalog.image_tasks_table.c.deadline_at, catalog.image_tasks_table.c.provider_http_status))).all()
        assert all(row.deadline_at and row.provider_http_status == 200 for row in rows)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    print(json.dumps({"concurrency": count, "success": len(results), "failed": 0,
                      "bytes_per_result": 2 * 1024 * 1024, "elapsed_s": round(perf_counter() - started, 3),
                      "end_to_end_p95_s": round(sorted(timings)[int(count * .95) - 1], 3),
                      "cpu_seconds": round(usage.ru_utime + usage.ru_stime - cpu_started.ru_utime - cpu_started.ru_stime, 3),
                      "peak_rss_raw": usage.ru_maxrss, "peaks": peaks}))
