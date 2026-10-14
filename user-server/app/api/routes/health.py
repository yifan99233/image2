import asyncio
from time import monotonic

from fastapi import APIRouter
from sqlalchemy import text

from app.core.redis import check_redis
from app.core.responses import ok
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["health"])
_HEALTH_CACHE_SECONDS = 5.0
_dependency_status_cache: tuple[float, dict[str, bool | str]] | None = None
_dependency_status_lock = asyncio.Lock()


async def _dependency_status() -> dict[str, bool | str]:
    global _dependency_status_cache
    now = monotonic()
    if _dependency_status_cache is not None and now - _dependency_status_cache[0] < _HEALTH_CACHE_SECONDS:
        return dict(_dependency_status_cache[1])

    # Collapse a burst of readiness probes into one DB query and one Redis
    # ping. The liveness endpoint remains completely dependency-free.
    async with _dependency_status_lock:
        now = monotonic()
        if _dependency_status_cache is not None and now - _dependency_status_cache[0] < _HEALTH_CACHE_SECONDS:
            return dict(_dependency_status_cache[1])
        status = await _check_dependencies()
        _dependency_status_cache = (monotonic(), status)
        return dict(status)


async def _check_dependencies() -> dict[str, bool | str]:
    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    redis_ok = await check_redis()
    return {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "database": db_ok,
        "redis": redis_ok,
    }


@router.get("/livez")
async def livez():
    """Cheap process liveness probe; use /healthz for dependency readiness."""
    return ok({"status": "ok"})


@router.get("/healthz")
async def healthz():
    return ok(await _dependency_status())
