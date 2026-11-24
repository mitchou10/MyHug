import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models import ModelFile, ModelVersion
from app.models.model_version import FAILED, PROCESSING, READY
from app.repositories.model_uploads import ModelUploadRepository
from app.repositories.model_versions import ModelVersionRepository
from app.services.errors import FingerprintMismatch, ModelVersionNotFound, NotBeingProcessed, UnreadableDataFile
from app.storage import ObjectStore

logger = logging.getLogger(__name__)
# A version that has waited less than this is left alone: the job that was queued for it is probably about to start.
GRACE = timedelta(minutes=2)


@dataclass(frozen=True)
class FileToCheck:
    """A file the worker has to fingerprint, and where to read it: an address of the storage, signed, short-lived."""

    id: uuid.UUID
    path: str
    size_bytes: int
    url: str


@dataclass(frozen=True)
class FileChecked:
    """What the worker found. The size is what it received: it must be the one that was announced."""

    id: uuid.UUID
    size_bytes: int
    sha256: str | None = None


class ModelProcessing:
    """What the worker asks of the API while it checks the files of a version of a model. The worker reads the files
    (it downloads them and computes their fingerprint); the API keeps the records: it takes the version in hand for one
    worker only, compares what was found with what was announced, makes the files that turn out to be duplicates
    point to one object, and says when the version is `ready`.

    - `claim`: one worker at a time (a second call, a lost job sent again, gets nothing).
    - `complete`: the fingerprints are written; a file that is not what was announced makes the version `failed`
      (the reason names it).
    - `fail`: the worker could not read a file, and it is the file's fault: the version is `failed` with the reason.
    - `release`: it could not, and it is not the file's fault (the storage was down): the version waits again."""

    def __init__(
        self,
        versions: ModelVersionRepository,
        uploads: ModelUploadRepository,
        store: ObjectStore,
        *,
        max_attempts: int = 3,
        stale: timedelta = timedelta(minutes=30),
        signed_seconds: int = 3600,
    ) -> None:
        self._versions = versions
        self._uploads = uploads
        self._store = store
        self._max_attempts = max_attempts
        self._stale = stale
        self._signed_seconds = signed_seconds

    async def claim(self, version_id: uuid.UUID) -> list[FileToCheck] | None:
        """Takes a version in hand and says what is to be read in it. None when it is not up for the taking (ready,
        being checked by another worker, unknown, given up after too many attempts, or with nothing left to read)."""
        version = await self._versions.claim(version_id, datetime.now(UTC) - self._stale)
        if version is None:
            return None
        if version.attempts > self._max_attempts:
            await self._finish(version, FAILED, "The check was interrupted too many times", set())
            return None
        wanted = [f for f in await self._versions.files(version.id) if f.sha256 is None]
        if not wanted:  # everything was known already
            await self._finish(version, READY, None, set())
            return None
        return [
            FileToCheck(
                id=file.id,
                path=file.path,
                size_bytes=file.size_bytes,
                url=await self._store.presign_get(file.storage_key, self._signed_seconds, internal=True),
            )
            for file in wanted
        ]

    async def complete(self, version_id: uuid.UUID, read: list[FileChecked]) -> ModelVersion:
        """Writes what the worker found. The version ends `ready`, or `failed` when a file is not what it should be."""
        version = await self._held(version_id)
        found = {item.id: item for item in read}
        obsolete: set[str] = set()  # objects that became duplicates: deleted once the files point elsewhere
        files = await self._versions.files(version.id)
        try:
            announced = await self._uploads.announced_fingerprints([f.id for f in files if f.sha256 is None])
            for file in files:
                if file.sha256 is None:
                    await self._write(version, file, found.get(file.id), announced.get(file.id), obsolete)
        except (UnreadableDataFile, FingerprintMismatch) as error:
            logger.warning("Model version %s did not pass the check: %s", version.id, error)
            await self._versions.rollback()  # nothing of what was written stays: the version is as it was, and failed
            return await self._failed(version_id, str(error))
        return await self._finish(version, READY, None, obsolete)

    async def fail(self, version_id: uuid.UUID, error: str) -> ModelVersion:
        version = await self._held(version_id)
        return await self._finish(version, FAILED, error[:2000], set())

    async def release(self, version_id: uuid.UUID) -> None:
        await self._versions.release(version_id)

    async def waiting(self, limit: int = 100) -> list[uuid.UUID]:
        """The versions nobody is checking: the worker queues them again. Its safety net, when Redis lost a job or a
        worker died."""
        now = datetime.now(UTC)
        return await self._versions.waiting(older_than=now - GRACE, stale_before=now - self._stale, limit=limit)

    async def _held(self, version_id: uuid.UUID) -> ModelVersion:
        version = await self._versions.get_by_id(version_id)
        if version is None:
            raise ModelVersionNotFound
        if version.status != PROCESSING:
            raise NotBeingProcessed
        return version

    async def _failed(self, version_id: uuid.UUID, error: str) -> ModelVersion:
        version = await self._held(version_id)
        return await self._finish(version, FAILED, error[:2000], set())

    async def _finish(self, version: ModelVersion, status: str, error: str | None, obsolete: set[str]) -> ModelVersion:
        version.status, version.error = status, error
        await self._versions.commit()
        for key in obsolete:  # the files point to the other object now
            await self._store.delete(key)
        return version

    async def _write(
        self,
        version: ModelVersion,
        file: ModelFile,
        read: FileChecked | None,
        announced: str | None,
        obsolete: set[str],
    ) -> None:
        if read is None:
            raise UnreadableDataFile(f"{file.path} was not read")
        if read.size_bytes != file.size_bytes:
            raise UnreadableDataFile(f"{file.path} is {read.size_bytes} bytes in the storage, not {file.size_bytes}")
        if not read.sha256:
            raise UnreadableDataFile(f"{file.path} has no fingerprint")
        if announced is not None and announced != read.sha256:
            raise FingerprintMismatch(f"{file.path} has the fingerprint {read.sha256}, not {announced} as announced")
        file.sha256 = read.sha256
        await self._versions.flush()
        twin = await self._versions.find_twin(version.model_id, read.sha256, file.size_bytes, file.storage_key)
        if twin is not None:
            # The model holds this content already: one object is enough, and whoever pointed to the duplicate points
            # there now.
            obsolete.add(file.storage_key)
            await self._versions.repoint(file.storage_key, twin.storage_key)
            file.storage_key = twin.storage_key
