import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.repositories.dataset_uploads import DatasetUploadRepository
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services.dataset_processing import DatasetProcessor
from app.services.factory import build_dataset_uploads
from app.storage import get_store
from app.worker.celery_app import celery_app
from app.worker.jobs import NoJobs
from app.worker.runtime import database

logger = logging.getLogger(__name__)
# A version that has waited less than this is left alone: the job that was queued for it is probably about to start.
GRACE = timedelta(minutes=2)
SWEEP_LIMIT = 100


async def _process(version_id: uuid.UUID) -> str | None:
    async with database() as db:
        processor = DatasetProcessor(
            DatasetRepository(db),
            DatasetVersionRepository(db),
            DatasetUploadRepository(db),
            get_store(),
            max_attempts=settings.PROCESSING_MAX_ATTEMPTS,
            stale=timedelta(minutes=settings.PROCESSING_STALE_MINUTES),
            temp_dir=settings.WORKER_TEMP_DIR or None,
        )
        version = await processor.process(version_id)
        return version.status if version else None


@celery_app.task(
    name="datasets.process_version",
    autoretry_for=(Exception,),  # what is not the file's fault: the storage or the database was down
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def process_version(version_id: str) -> str | None:
    """Reads the files of a version. Returns where it ended (`ready`, `failed`) or None."""
    return asyncio.run(_process(uuid.UUID(version_id)))


async def _waiting() -> list[uuid.UUID]:
    now = datetime.now(UTC)
    async with database() as db:
        return await DatasetVersionRepository(db).waiting(
            older_than=now - GRACE,
            stale_before=now - timedelta(minutes=settings.PROCESSING_STALE_MINUTES),
            limit=SWEEP_LIMIT,
        )


@celery_app.task(name="datasets.process_waiting")
def process_waiting() -> int:
    """Queues the reading of the versions nobody is reading. Returns how many."""
    waiting = asyncio.run(_waiting())
    for version_id in waiting:
        process_version.apply_async(args=[str(version_id)])
    return len(waiting)


async def _expire() -> int:
    async with database() as db:
        return await build_dataset_uploads(db, get_store(), NoJobs()).expire_stale()


@celery_app.task(name="datasets.expire_uploads")
def expire_uploads() -> int:
    """Gives up the uploads that took too long and frees what they had received. Returns how many."""
    return asyncio.run(_expire())
