import asyncio

from redis.asyncio import Redis

from app.core.config import settings

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=True,
    max_connections=max(1, int(settings.redis_max_connections)),
)


async def check_redis(timeout: float = 0.3) -> bool:
    try:
        return bool(await asyncio.wait_for(redis_client.ping(), timeout=timeout))
    except Exception:
        return False
