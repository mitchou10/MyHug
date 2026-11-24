"""How the services of the datasets are put together. The routes and the worker build them the same way."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.dataset_uploads import DatasetUploadRepository
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services.dataset_access import DatasetAccess
from app.services.dataset_uploads import DatasetUploadService
from app.services.dataset_versions import DatasetVersionService
from app.services.datasets import DatasetService
from app.storage import ObjectStore
from app.worker.jobs import Jobs


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
