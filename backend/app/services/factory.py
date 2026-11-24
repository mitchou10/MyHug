"""How the services of the datasets are put together. The routes and the worker build them the same way."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs import Jobs
from app.repositories.dataset_derivatives import DatasetDerivativeRepository
from app.repositories.dataset_uploads import DatasetUploadRepository
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.repositories.storage_references import StorageReferenceRepository
from app.services.dataset_access import DatasetAccess
from app.services.dataset_derivatives import DatasetDerivatives
from app.services.dataset_processing import DatasetProcessing
from app.services.dataset_uploads import DatasetUploadService
from app.services.dataset_versions import DatasetVersionService
from app.services.datasets import DatasetService
from app.services.storage_garbage import StorageGarbage
from app.storage import ObjectStore


def build_datasets(db: AsyncSession, store: ObjectStore) -> DatasetService:
    datasets = DatasetRepository(db)
    return DatasetService(
        datasets, DatasetAccess(datasets), DatasetVersionRepository(db), DatasetUploadRepository(db), store
    )


def build_dataset_versions(db: AsyncSession, store: ObjectStore, jobs: Jobs) -> DatasetVersionService:
    datasets = DatasetRepository(db)
    return DatasetVersionService(
        datasets,
        DatasetVersionRepository(db),
        DatasetAccess(datasets),
        store,
        max_bytes=settings.DATASET_FILE_MAX_BYTES,
        max_files=settings.DATASET_VERSION_MAX_FILES,
        signed_seconds=settings.SIGNED_ADDRESS_SECONDS,
        jobs=jobs,
        derivatives=build_dataset_derivatives(db, store),
    )


def build_dataset_uploads(db: AsyncSession, store: ObjectStore, jobs: Jobs) -> DatasetUploadService:
    datasets = DatasetRepository(db)
    return DatasetUploadService(
        datasets,
        DatasetUploadRepository(db),
        build_dataset_versions(db, store, jobs),
        DatasetAccess(datasets),
        store,
        max_bytes=settings.DATASET_UPLOAD_MAX_BYTES,
        max_files=settings.DATASET_VERSION_MAX_FILES,
        part_bytes=settings.UPLOAD_PART_BYTES,
        session=timedelta(hours=settings.UPLOAD_SESSION_HOURS),
        signed_seconds=settings.SIGNED_ADDRESS_SECONDS,
        jobs=jobs,
    )


def build_dataset_derivatives(db: AsyncSession, store: ObjectStore) -> DatasetDerivatives:
    return DatasetDerivatives(
        DatasetDerivativeRepository(db),
        store,
        min_bytes=settings.DERIVATIVE_MIN_BYTES,
        max_bytes=settings.DERIVATIVE_MAX_SOURCE_BYTES,
        part_bytes=settings.DERIVATIVE_PART_BYTES,
        max_attempts=settings.PROCESSING_MAX_ATTEMPTS,
        stale=timedelta(minutes=settings.PROCESSING_STALE_MINUTES),
        signed_seconds=settings.SIGNED_ADDRESS_SECONDS,
    )


def build_dataset_processing(db: AsyncSession, store: ObjectStore, jobs: Jobs | None = None) -> DatasetProcessing:
    return DatasetProcessing(
        DatasetRepository(db),
        DatasetVersionRepository(db),
        DatasetUploadRepository(db),
        store,
        max_attempts=settings.PROCESSING_MAX_ATTEMPTS,
        stale=timedelta(minutes=settings.PROCESSING_STALE_MINUTES),
        signed_seconds=settings.SIGNED_ADDRESS_SECONDS,
        derivatives=build_dataset_derivatives(db, store),
        jobs=jobs,
    )


def garbage_grace() -> timedelta:
    """How old an object must be to be garbage: longer than an upload session, whatever is configured."""
    return timedelta(hours=max(settings.STORAGE_GC_GRACE_HOURS, settings.UPLOAD_SESSION_HOURS + 12))


def build_storage_garbage(db: AsyncSession, store: ObjectStore) -> StorageGarbage:
    return StorageGarbage(
        StorageReferenceRepository(db),
        store,
        grace=garbage_grace(),
        max_scanned=settings.STORAGE_GC_MAX_SCANNED,
        max_deletions=settings.STORAGE_GC_MAX_DELETIONS,
        check_rows=settings.STORAGE_GC_CHECK_ROWS,
    )
