"""The worker is a service of the platform, not a user: it is known by an API key."""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import settings

MIN_KEY_LENGTH = 16


async def require_worker(
    x_api_key: Annotated[str | None, Header(description="The key of the worker")] = None,
) -> None:
    """Dependency: 401 unless the `X-Api-Key` is the worker's. No key configured: nobody gets in."""
    expected = settings.WORKER_API_KEY
    if x_api_key and len(expected) >= MIN_KEY_LENGTH and hmac.compare_digest(expected.encode(), x_api_key.encode()):
        return
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Unknown or missing API key", headers={"WWW-Authenticate": "ApiKey"}
    )


Worker = Annotated[None, Depends(require_worker)]
