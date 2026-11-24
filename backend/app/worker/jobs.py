import asyncio
import logging
import uuid
from typing import Protocol

logger = logging.getLogger(__name__)


class Jobs(Protocol):
    """What the API asks of the worker. A request never waits for the work: it only says that there is some."""

    async def process_version(self, version_id: uuid.UUID) -> None:
        """A version was recorded: its files are to be read."""
        ...


class NoJobs:
    """Nothing is queued (tests, scripts): the versions wait until something reads them."""

    async def process_version(self, version_id: uuid.UUID) -> None:
        return None


class CeleryJobs:
    """Queues the jobs in Redis. If Redis is down the request still succeeds: the version waits, and the job that looks
    for waiting versions (`datasets.process_waiting`) queues it when the queue is back."""

    async def process_version(self, version_id: uuid.UUID) -> None:
        from app.worker.tasks import (
            process_version,
        )  # not at import: Celery is heavy and the API does not always need it

        try:
            await asyncio.to_thread(process_version.apply_async, args=[str(version_id)])
        except Exception:
            logger.exception("Could not queue the reading of version %s: the sweep will find it", version_id)
