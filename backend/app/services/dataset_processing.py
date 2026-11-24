import logging
import uuid

from app.models import DatasetFile, DatasetVersion
from app.models.dataset_version import FAILED, PROCESSING, READY
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services import tables
from app.services.errors import DatasetFileNotFound, UnreadableDataFile
from app.storage import ObjectStore

logger = logging.getLogger(__name__)
MEDIA = ("image/", "audio/", "video/")


class DatasetProcessor:
    """Reads the files of a version to find what they hold: the rows of each, their columns, their part of the dataset,
    and how many items the version has in all. Then the version is `ready`.

    This is the work of a worker, not of the API: the API only records the files, and a version stays `pending` until
    a worker calls `process`. It is safe to call again (a version that is ready is left alone) and it skips the files
    that were already read in an earlier version, which are the same files."""

    def __init__(self, datasets: DatasetRepository, versions: DatasetVersionRepository, store: ObjectStore) -> None:
        self._datasets = datasets
        self._versions = versions
        self._store = store

    async def process(self, version_id: uuid.UUID) -> DatasetVersion | None:
        """Returns the version as it ended (`ready` or `failed`), or None if there is no such version.

        A file that cannot be read does not raise: the version is `failed`, with the reason in `error`."""
        version = await self._versions.get_by_id(version_id)
        if version is None:
            return None
        if version.status == READY:
            return version
        version.status, version.error = PROCESSING, None
        await self._versions.commit()  # others see it is being read

        files = await self._versions.files(version.id)
        try:
            for file in files:
                if tables.is_data_file(file.path) and file.rows is None:
                    await self._read(file)
        except (UnreadableDataFile, DatasetFileNotFound) as error:
            logger.warning("Dataset version %s cannot be read: %s", version.id, error)
            version.status, version.error = FAILED, str(error)
        else:
            self._summarize(version, files)
            # The list shows what the latest version holds: a version that is not the latest changes nothing there.
            dataset = await self._datasets.get(version.dataset_id)
            if dataset is not None and dataset.version == version.number:
                dataset.rows = version.rows
        await self._versions.commit()
        return version

    async def _read(self, file: DatasetFile) -> None:
        stored = await self._store.get(file.storage_key)
        if stored is None:
            raise DatasetFileNotFound(f"{file.path} is missing from the storage")
        info = tables.inspect(file.path, stored.data)
        file.split, file.rows = tables.split_of(file.path), info.rows
        file.columns = [{"name": column.name, "dtype": column.dtype} for column in info.columns]

    def _summarize(self, version: DatasetVersion, files: list[DatasetFile]) -> None:
        """What the version holds: the rows of its data files, or else how many images, sounds and videos."""
        data = sorted((f for f in files if f.split is not None), key=lambda f: (_order(f.split), f.path))
        version.rows = (
            sum(f.rows or 0 for f in data) if data else sum(1 for f in files if f.content_type.startswith(MEDIA))
        )
        # The preview shows the columns of the first file of the first part.
        version.columns = data[0].columns if data else []
        version.status = READY


def _order(split: str | None) -> int:
    order = ("train", "validation", "test")
    return order.index(split) if split in order else len(order)
