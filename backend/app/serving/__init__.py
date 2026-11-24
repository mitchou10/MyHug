from functools import lru_cache

from app.config import settings
from app.serving.client import Prediction, ServingClient
from app.serving.limits import MemoryRateLimiter, RateLimiter, RedisRateLimiter


def get_serving_client() -> ServingClient:
    """The client of the servers of the models, from the settings. Used as a FastAPI dependency; tests replace it."""
    return ServingClient(
        origins=settings.MODEL_SERVING_ORIGINS,
        timeout=settings.SERVING_TIMEOUT_SECONDS,
        max_response_bytes=settings.SERVING_MAX_RESPONSE_BYTES,
    )


@lru_cache(maxsize=1)
def _redis_limiter(url: str) -> RedisRateLimiter:
    return RedisRateLimiter(url)


def get_rate_limiter() -> RateLimiter:
    """The count of the calls of each person: shared by the processes through Redis. Tests replace it."""
    return _redis_limiter(settings.REDIS_URL)


__all__ = [
    "MemoryRateLimiter",
    "Prediction",
    "RateLimiter",
    "RedisRateLimiter",
    "ServingClient",
    "get_rate_limiter",
    "get_serving_client",
]
