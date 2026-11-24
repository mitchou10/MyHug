import logging
import time
from collections import defaultdict, deque
from typing import Protocol

logger = logging.getLogger(__name__)


class RateLimiter(Protocol):
    async def allow(self, key: str, limit: int, seconds: int = 60) -> bool:
        """Counts one call by `key` and says whether it is within `limit` calls in the last `seconds`."""
        ...


class MemoryRateLimiter:
    """In the memory of the process (tests, a single process). Several processes each have their own count."""

    def __init__(self) -> None:
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    async def allow(self, key: str, limit: int, seconds: int = 60) -> bool:
        now = time.monotonic()
        calls = self._calls[key]
        while calls and calls[0] <= now - seconds:
            calls.popleft()
        if len(calls) >= limit:
            return False
        calls.append(now)
        return True


class RedisRateLimiter:
    """The same count for every process of the backend, in Redis (a window that starts at the first call). If Redis does
    not answer the call is let through: trying a model must not depend on it, and the endpoint has its own limits."""

    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url)

    async def allow(self, key: str, limit: int, seconds: int = 60) -> bool:
        try:
            name = f"rate:{key}"
            count = await self._redis.incr(name)
            if count == 1:
                await self._redis.expire(name, seconds)
            return count <= limit
        except Exception:
            logger.exception("The rate limit could not be counted: the call goes through")
            return True
