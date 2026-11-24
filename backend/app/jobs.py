"""What the API asks of the worker. The worker is another service: the API only puts a job in Redis, by the name of the
task, and does not know its code. Nobody waits for the work: a request only says that there is some."""

import asyncio
import logging
import uuid
from typing import Protocol

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)
# The names the worker registers its tasks under (see `worker/worker/tasks.py`).
PROCESS_VERSION = "datasets.process_version"
QUEUE = "datasets"


class Jobs(Protocol):
    async def process_version(self, version_id: uuid.UUID) -> None:
        """A version was recorded: its files are to be read."""
        ...


class NoJobs:
    """Nothing is queued (tests, scripts): the versions wait until something reads them."""

    async def process_version(self, version_id: uuid.UUID) -> None:
        return None


class CeleryJobs:
    """Queues the jobs in Redis. If Redis is down the request still succeeds: the version waits, and the worker's sweep
    (it asks `/api/internal/dataset-versions/waiting`) queues it when the queue is back."""

    def __init__(self) -> None:
        self._client: Celery | None = None

    def _celery(self) -> Celery:
        if self._client is None:
            self._client = Celery("app", broker=settings.REDIS_URL, set_as_current=False)
        return self._client

    async def process_version(self, version_id: uuid.UUID) -> None:
        try:
            await asyncio.to_thread(self._celery().send_task, PROCESS_VERSION, args=[str(version_id)], queue=QUEUE)
        except Exception:
            logger.exception("Could not queue the reading of version %s: the sweep will find it", version_id)
