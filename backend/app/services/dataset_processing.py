import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.jobs import Jobs, NoJobs
from app.models import DatasetFile, DatasetVersion
from app.models.dataset_version import FAILED, PROCESSING, READY
from app.repositories.dataset_uploads import DatasetUploadRepository
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services import tables
from app.services.dataset_derivatives import DatasetDerivatives
from app.services.errors import FingerprintMismatch, NotBeingProcessed, UnreadableDataFile, VersionNotFound
from app.storage import ObjectStore

logger = logging.getLogger(__name__)
MEDIA = ("image/", "audio/", "video/")
# A version that has waited less than this is left alone: the job that was queued for it is probably about to start.
GRACE = timedelta(minutes=2)


@dataclass(frozen=True)
class FileToRead:
    """A file the worker has to read, and where to read it: an address of the storage, signed, short-lived."""

    id: uuid.UUID
    path: str
    size_bytes: int
    url: str
    needs_fingerprint: bool
    needs_rows: bool


@dataclass(frozen=True)
class FileRead:
    """What the worker found in a file. The size is what it received: it must be the one that was announced."""

    id: uuid.UUID
    size_bytes: int
    sha256: str | None = None
    rows: int | None = None
    columns: list[tables.Column] | None = None


class DatasetProcessing:
    """What the worker asks of the API while it reads the files of a version. The worker reads (it downloads, counts,
    computes fingerprints); the API keeps the records: it takes the version in hand for one worker only, checks and
    writes what was found, makes the files that became duplicates point to one object, and says when it is `ready`.

    - `claim`: one worker at a time (a second call, a lost job sent again, gets nothing).
    - `complete`: what was read is written; a file that is not what was announced makes the version `failed`.
    - `fail`: the worker could not read a file, and it is the file's fault: the version is `failed` with the reason.
    - `release`: it could not, and it is not the file's fault (the storage was down): the version waits again."""

    def __init__(
        self,
        datasets: DatasetRepository,
        versions: DatasetVersionRepository,
        uploads: DatasetUploadRepository,
        store: ObjectStore,
        *,
        max_attempts: int = 3,
        stale: timedelta = timedelta(minutes=30),
        signed_seconds: int = 3600,
        derivatives: DatasetDerivatives | None = None,
        jobs: Jobs | None = None,
    ) -> None:
        self._datasets = datasets
        self._versions = versions
        self._uploads = uploads
        self._store = store
        self._max_attempts = max_attempts
        self._stale = stale
        self._signed_seconds = signed_seconds
        self._derivatives = derivatives
        self._jobs: Jobs = jobs or NoJobs()

    async def claim(self, version_id: uuid.UUID) -> list[FileToRead] | None:
        """Takes a version in hand and says what is to be read in it. None when it is not up for the taking (ready,
        being read by another worker, unknown, given up after too many attempts, or with nothing left to read)."""
        version = await self._versions.claim(version_id, datetime.now(UTC) - self._stale)
        if version is None:
            return None
        if version.attempts > self._max_attempts:
            await self._finish(version, FAILED, "The reading was interrupted too many times", set())
            return None
        files = await self._versions.files(version.id)
        wanted = [f for f in files if self._needs_fingerprint(f) or self._needs_rows(f)]
        if not wanted:  # everything was read in an earlier version
            self._summarize(version, files)
            await self._finish(version, READY, None, set())
            return None
        return [
            FileToRead(
                id=file.id,
                path=file.path,
                size_bytes=file.size_bytes,
                url=await self._store.presign_get(file.storage_key, self._signed_seconds, internal=True),
                needs_fingerprint=self._needs_fingerprint(file),
                needs_rows=self._needs_rows(file),
            )
            for file in wanted
        ]

    async def complete(self, version_id: uuid.UUID, read: list[FileRead]) -> DatasetVersion:
        """Writes what the worker found. The version ends `ready`, or `failed` when a file is not what it should be."""
        version = await self._held(version_id)
        found = {item.id: item for item in read}
        obsolete: set[str] = set()  # objects that became duplicates: deleted once the files point elsewhere
        files = await self._versions.files(version.id)
        try:
            announced = await self._uploads.announced_fingerprints([f.id for f in files if f.sha256 is None])
            for file in files:
                await self._write(version, file, found.get(file.id), announced.get(file.id), obsolete)
        except (UnreadableDataFile, FingerprintMismatch) as error:
            logger.warning("Dataset version %s cannot be read: %s", version.id, error)
            return await self._finish(version, FAILED, str(error), obsolete)
        self._summarize(version, files)
        return await self._finish(version, READY, None, obsolete)

    async def fail(self, version_id: uuid.UUID, error: str) -> DatasetVersion:
        version = await self._held(version_id)
        return await self._finish(version, FAILED, error[:2000], set())

    async def release(self, version_id: uuid.UUID) -> None:
        await self._versions.release(version_id)

    async def waiting(self, limit: int = 100) -> list[uuid.UUID]:
        """The versions nobody is reading: the worker queues them again. Its safety net, when Redis lost a job or a
        worker died."""
        now = datetime.now(UTC)
        return await self._versions.waiting(older_than=now - GRACE, stale_before=now - self._stale, limit=limit)

    async def _held(self, version_id: uuid.UUID) -> DatasetVersion:
        version = await self._versions.get_by_id(version_id)
        if version is None:
            raise VersionNotFound
        if version.status != PROCESSING:
            raise NotBeingProcessed
        return version

    @staticmethod
    def _needs_fingerprint(file: DatasetFile) -> bool:
        return file.sha256 is None

    @staticmethod
    def _needs_rows(file: DatasetFile) -> bool:
        return tables.is_data_file(file.path) and file.rows is None

    async def _finish(
        self, version: DatasetVersion, status: str, error: str | None, obsolete: set[str]
    ) -> DatasetVersion:
        version.status, version.error = status, error
        if status == READY:
            # The list shows what the latest version holds: a version that is not the latest changes nothing there.
            dataset = await self._datasets.get(version.dataset_id)
            if dataset is not None and dataset.version == version.number:
                dataset.rows = version.rows
        copies = await self._copies_wanted(version) if status == READY else []
        await self._versions.commit()
        for copy in copies:  # queued once the version is recorded, so the worker finds it
            await self._jobs.convert_file(copy)
        for key in obsolete:  # the files point to the other object now
            await self._store.delete(key)
        return version

    async def _copies_wanted(self, version: DatasetVersion) -> list[uuid.UUID]:
        """Makes the records of the Parquet copies the files of this version need (the big tabular ones)."""
        if self._derivatives is None:
            return []
        return await self._derivatives.create_for(await self._versions.files(version.id))

    async def _write(
        self,
        version: DatasetVersion,
        file: DatasetFile,
        read: FileRead | None,
        announced: str | None,
        obsolete: set[str],
    ) -> None:
        needs_fingerprint, needs_rows = self._needs_fingerprint(file), self._needs_rows(file)
        if not (needs_fingerprint or needs_rows):
            return
        if read is None:
            raise UnreadableDataFile(f"{file.path} was not read")
        if read.size_bytes != file.size_bytes:
            raise UnreadableDataFile(f"{file.path} is {read.size_bytes} bytes in the storage, not {file.size_bytes}")
        if needs_fingerprint:
            if not read.sha256:
                raise UnreadableDataFile(f"{file.path} has no fingerprint")
            await self._fingerprint(version, file, read.sha256, announced, obsolete)
        if needs_rows:
            if read.rows is None or read.columns is None:
                raise UnreadableDataFile(f"{file.path} was not counted")
            file.split, file.rows = tables.split_of(file.path), read.rows
            file.columns = [{"name": column.name, "dtype": column.dtype} for column in read.columns]

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
