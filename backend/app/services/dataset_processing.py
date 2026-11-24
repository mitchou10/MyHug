import asyncio
import hashlib
import logging
import tempfile
import uuid
from datetime import UTC, datetime, timedelta

from app.models import DatasetFile, DatasetVersion
from app.models.dataset_version import FAILED, READY
from app.repositories.dataset_uploads import DatasetUploadRepository
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services import tables
from app.services.errors import DatasetFileNotFound, FingerprintMismatch, UnreadableDataFile
from app.storage import ObjectNotFound, ObjectStore

logger = logging.getLogger(__name__)
MEDIA = ("image/", "audio/", "video/")
# What makes a version fail for good: the files are what they are, reading them again would give the same.
FILE_PROBLEMS = (UnreadableDataFile, DatasetFileNotFound, FingerprintMismatch)


class DatasetProcessor:
    """Reads the files of a version to find what they hold, then the version is `ready`. This is the work of the worker.

    For each file it has not seen yet: it brings the content to a file on disk as it comes (never whole in memory),
    computes its fingerprint (sha256), compares it with the one the browser announced, and, if it holds rows (csv, tsv,
    jsonl, parquet), counts them and finds the columns. If the dataset already holds another object with the same
    fingerprint, the file points to it and the duplicate is deleted. Then it adds up what the version holds.

    - One worker at a time: the version is claimed, so a second call (a lost job sent again) does nothing.
    - It can be played again: a file that was read in an earlier version (the same object) is not read again.
    - A file that cannot be read makes the version `failed`, with the reason; a failure that is not its fault (the
      storage is down) puts the version back to waiting and raises, so the job is tried again."""

    def __init__(
        self,
        datasets: DatasetRepository,
        versions: DatasetVersionRepository,
        uploads: DatasetUploadRepository,
        store: ObjectStore,
        *,
        max_attempts: int = 3,
        stale: timedelta = timedelta(minutes=30),
        temp_dir: str | None = None,
    ) -> None:
        self._datasets = datasets
        self._versions = versions
        self._uploads = uploads
        self._store = store
        self._max_attempts = max_attempts
        self._stale = stale
        self._temp_dir = temp_dir or None

    async def process(self, version_id: uuid.UUID) -> DatasetVersion | None:
        """The version as it ends up: `ready` or `failed`. Or as it is, when it is not up for the taking (ready, or
        another worker has it); None if there is no such version."""
        version = await self._versions.claim(version_id, datetime.now(UTC) - self._stale)
        if version is None:
            return await self._versions.get_by_id(version_id)
        if version.attempts > self._max_attempts:
            return await self._finish(version, FAILED, "The reading was interrupted too many times", set())

        obsolete: set[str] = set()  # objects that became duplicates: deleted once the files point elsewhere
        try:
            files = await self._versions.files(version.id)
            announced = await self._uploads.announced_fingerprints([f.id for f in files if f.sha256 is None])
            for file in files:
                await self._read(version, file, announced.get(file.id), obsolete)
        except FILE_PROBLEMS as error:
            logger.warning("Dataset version %s cannot be read: %s", version.id, error)
            return await self._finish(version, FAILED, str(error), obsolete)
        except Exception:
            await self._versions.rollback()
            await self._versions.release(version.id)  # not the file's fault: it will be taken again
            raise
        self._summarize(version, files)
        return await self._finish(version, READY, None, obsolete)

    async def _finish(
        self, version: DatasetVersion, status: str, error: str | None, obsolete: set[str]
    ) -> DatasetVersion:
        version.status, version.error = status, error
        if status == READY:
            # The list shows what the latest version holds: a version that is not the latest changes nothing there.
            dataset = await self._datasets.get(version.dataset_id)
            if dataset is not None and dataset.version == version.number:
                dataset.rows = version.rows
        await self._versions.commit()
        for key in obsolete:  # the files point to the other object now
            await self._store.delete(key)
        return version

    async def _read(
        self, version: DatasetVersion, file: DatasetFile, announced: str | None, obsolete: set[str]
    ) -> None:
        needs_fingerprint = file.sha256 is None
        needs_rows = tables.is_data_file(file.path) and file.rows is None
        if not (needs_fingerprint or needs_rows):
            return
        with tempfile.TemporaryFile(dir=self._temp_dir) as handle:
            digest, size = hashlib.sha256(), 0
            try:
                async for chunk in self._store.stream(file.storage_key):
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            except ObjectNotFound:
                raise DatasetFileNotFound(f"{file.path} is missing from the storage") from None
            if size != file.size_bytes:
                raise UnreadableDataFile(f"{file.path} is {size} bytes in the storage, not {file.size_bytes}")
            if needs_fingerprint:
                await self._fingerprint(version, file, digest.hexdigest(), announced, obsolete)
            if needs_rows:
                info = await asyncio.to_thread(tables.inspect, file.path, handle)  # a large file takes a while to count
                file.split, file.rows = tables.split_of(file.path), info.rows
                file.columns = [{"name": column.name, "dtype": column.dtype} for column in info.columns]

    async def _fingerprint(
        self, version: DatasetVersion, file: DatasetFile, computed: str, announced: str | None, obsolete: set[str]
    ) -> None:
        if announced is not None and announced != computed:
            raise FingerprintMismatch(f"{file.path} has the fingerprint {computed}, not {announced} as announced")
        file.sha256 = computed
        await self._versions.flush()
        twin = await self._versions.find_twin(version.dataset_id, computed, file.size_bytes, file.storage_key)
        if twin is not None:
            # The dataset holds this content already: one object is enough, and whoever pointed to the duplicate
            # points there now.
            obsolete.add(file.storage_key)
            await self._versions.repoint(file.storage_key, twin.storage_key)
            file.storage_key = twin.storage_key

    @staticmethod
    def _summarize(version: DatasetVersion, files: list[DatasetFile]) -> None:
        """What the version holds: the rows of its data files, or else how many images, sounds and videos."""
        data = sorted((f for f in files if f.split is not None), key=lambda f: (_order(f.split), f.path))
        count = sum(f.rows or 0 for f in data) if data else sum(1 for f in files if f.content_type.startswith(MEDIA))
        version.rows = count
        # The preview shows the columns of the first file of the first part.
        version.columns = data[0].columns if data else []


def _order(split: str | None) -> int:
    order = ("train", "validation", "test")
    return order.index(split) if split in order else len(order)
