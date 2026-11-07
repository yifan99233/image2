import time

from app.core.config import settings
from app.core.redis import redis_client

_memory_attempts: dict[str, list[float]] = {}


async def login_rate_limit_key(identifier: str) -> bool:
    limit = settings.login_rate_limit_max_attempts
    window = settings.login_rate_limit_window_seconds
    key = f"login:attempts:{identifier}"
    try:
        current = await redis_client.incr(key)
        if current == 1:
            await redis_client.expire(key, window)
        return int(current) <= limit
    except Exception:
        now = time.monotonic()
        attempts = [value for value in _memory_attempts.get(identifier, []) if now - value < window]
        attempts.append(now)
        _memory_attempts[identifier] = attempts
        return len(attempts) <= limit
