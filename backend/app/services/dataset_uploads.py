import math
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from app.models import DatasetFile, DatasetUpload, DatasetUploadFile, DatasetVersion
from app.models.dataset_upload import ABORTED, COMPLETED, EXPIRED, OPEN
from app.repositories.dataset_uploads import DatasetUploadRepository
from app.repositories.datasets import DatasetRepository
from app.services.actor import Actor
from app.services.dataset_access import DatasetAccess
from app.services.dataset_versions import README, DatasetVersionService, clean_path
from app.services.errors import (
    EmptyFile,
    FileTooLarge,
    InvalidFilePath,
    NothingToCommit,
    TooManyFiles,
    UploadClosed,
    UploadIncomplete,
    UploadNotFound,
)
from app.storage import ObjectStore, PartInfo
from app.worker.jobs import Jobs, NoJobs

MIB = 1024 * 1024
S3_MIN_PART = 5 * MIB  # smaller than this, a part is refused unless it is the last
S3_MAX_PARTS = 10_000
README_MAX_BYTES = MIB  # a README is read to become the card: a huge one is not


class PlannedFile(BaseModel):
    """A file the browser announces it will send."""

    path: str
    size: int
    content_type: str | None = None
    # Its fingerprint, if the browser knows it: a file that is already in the dataset is not sent again.
    sha256: str | None = None


@dataclass(frozen=True)
class UploadView:
    upload: DatasetUpload
    files: list[DatasetUploadFile]
    # What reached the storage so far, by file: only when asked (it is a call to the storage for each file).
    received: dict[uuid.UUID, list[PartInfo]] | None = None


def part_size_for(size: int, preferred: int) -> int:
    """How big the parts of a file are: the preferred size, or bigger when the file is so large that it would need more
    parts than the storage allows. Always a whole number of MiB, never under what the storage accepts."""
    needed = math.ceil(size / S3_MAX_PARTS)
    return max(S3_MIN_PART, preferred, math.ceil(needed / MIB) * MIB)


class DatasetUploadService:
    """Sending files to a dataset, straight from the browser to the storage.

    `start` announces the files and gets them ready; the browser asks for a signed address for each part (`part_urls`),
    sends the parts, and can ask what arrived (`get`) to resume after a cut; `complete` puts the parts together, checks
    the sizes and makes the version (which a worker reads afterwards). An upload that goes on too long is given up."""

    def __init__(
        self,
        datasets: DatasetRepository,
        uploads: DatasetUploadRepository,
        versions: DatasetVersionService,
        access: DatasetAccess,
        store: ObjectStore,
        *,
        max_bytes: int,
        max_files: int,
        part_bytes: int,
        session: timedelta,
        signed_seconds: int,
        jobs: Jobs | None = None,
    ) -> None:
        self._datasets = datasets
        self._uploads = uploads
        self._versions = versions
        self._access = access
        self._store = store
        self._max_bytes = max_bytes
        self._max_files = max_files
        self._part_bytes = part_bytes
        self._session = session
        self._signed_seconds = signed_seconds
        self._jobs: Jobs = jobs or NoJobs()

    # ---- starting

    async def start(
        self, actor: Actor, owner: str, name: str, *, files: list[PlannedFile], remove: list[str], message: str
    ) -> UploadView:
        """Announces the files. Raises what is wrong with them (path, size, number) before anything is prepared."""
        dataset = await self._access.get_editable(actor, owner, name)
        if not files and not remove:
            raise NothingToCommit
        paths = [clean_path(file.path) for file in files]
        if len(paths) > self._max_files:
            raise TooManyFiles
        if len(set(paths)) != len(paths):
            raise InvalidFilePath
        if any(file.size <= 0 for file in files):
            raise EmptyFile
        if any(file.size > self._max_bytes for file in files):
            raise FileTooLarge
        await self._versions.plan(dataset, paths, remove)  # the paths to remove must be there, and the total is checked

        upload = DatasetUpload(
            id=uuid.uuid4(),
            dataset_id=dataset.id,
            remove=[clean_path(path) for path in remove],
            message=message,
            created_by=actor.user_id,
            created_by_username=actor.username,
            expires_at=datetime.now(UTC) + self._session,
        )
        prepared: list[DatasetUploadFile] = []
        try:
            for path, planned in zip(paths, files, strict=True):
                file_id = uuid.uuid4()
                content_type = planned.content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
                stored = None
                if planned.sha256:
                    stored = await self._versions.find_stored(dataset, planned.sha256, planned.size)
                if stored is not None:
                    # The dataset already holds this file: the new path points to the same object, nothing is sent.
                    row = DatasetUploadFile(
                        id=file_id,
                        upload_id=upload.id,
                        path=path,
                        size_bytes=planned.size,
                        content_type=stored.content_type,
                        storage_key=stored.storage_key,
                        sha256=planned.sha256,
                        multipart_id=None,
                        part_size=0,
                        parts_count=0,
                    )
                else:
                    key = f"datasets/{dataset.id}/files/{file_id}"
                    size = part_size_for(planned.size, self._part_bytes)
                    multipart_id = await self._store.create_multipart(key, content_type)
                    row = DatasetUploadFile(
                        id=file_id,
                        upload_id=upload.id,
                        path=path,
                        size_bytes=planned.size,
                        content_type=content_type,
                        storage_key=key,
                        sha256=planned.sha256,
                        multipart_id=multipart_id,
                        part_size=size,
                        parts_count=math.ceil(planned.size / size),
                    )
                prepared.append(row)
            self._uploads.add(upload)
            await self._uploads.flush()
            for row in prepared:
                self._uploads.add_file(row)
            await self._uploads.commit()
        except Exception:
            await self._abort_all(prepared)
            raise
        return UploadView(upload, prepared)

    # ---- during

    async def _open(self, actor: Actor, upload_id: uuid.UUID) -> tuple[DatasetUpload, list[DatasetUploadFile]]:
        """An upload of this person, still open. Raises UploadNotFound (not theirs), UploadClosed, and the errors of a
        dataset they can no longer change."""
        upload = await self._uploads.get(upload_id)
        if upload is None or not (upload.created_by == actor.user_id or actor.is_admin):
            raise UploadNotFound
        dataset = await self._datasets.get(upload.dataset_id)
        if dataset is None:
            raise UploadNotFound
        await self._access.require_editable(actor, dataset)
        if upload.status == OPEN and upload.expires_at <= datetime.now(UTC):
            await self._give_up(upload, EXPIRED)
        if upload.status != OPEN:
            raise UploadClosed
        return upload, await self._uploads.files(upload.id)

    async def get(self, actor: Actor, upload_id: uuid.UUID, *, parts: bool = False) -> UploadView:
        """The upload as it stands. With `parts`, which parts of each file reached the storage: what to resume from."""
        upload = await self._uploads.get(upload_id)
        if upload is None or not (upload.created_by == actor.user_id or actor.is_admin):
            raise UploadNotFound
        files = await self._uploads.files(upload.id)
        received = None
        if parts and upload.status == OPEN:
            received = {
                file.id: []
                if file.multipart_id is None
                else await self._store.list_parts(file.storage_key, file.multipart_id)
                for file in files
            }
        return UploadView(upload, files, received)

    async def part_urls(
        self, actor: Actor, upload_id: uuid.UUID, file_id: uuid.UUID, numbers: list[int]
    ) -> list[tuple[int, str]]:
        """The signed addresses to which the browser sends these parts of a file."""
        _, files = await self._open(actor, upload_id)
        file = next((f for f in files if f.id == file_id), None)
        if file is None:
            raise UploadNotFound
        if file.multipart_id is None:
            raise UploadIncomplete(f"{file.path} is already stored in the dataset: there is nothing to send")
        multipart_id = file.multipart_id
        if any(not 1 <= number <= file.parts_count for number in numbers):
            raise UploadIncomplete(
                f"{file.path} has {file.parts_count} parts: ask for a number from 1 to {file.parts_count}"
            )
        return [
            (number, await self._store.presign_part(file.storage_key, multipart_id, number, self._signed_seconds))
            for number in numbers
        ]

    # ---- finishing

    async def complete(self, actor: Actor, upload_id: uuid.UUID) -> DatasetVersion:
        """Puts the parts of every file together and makes the version. Playing it again after it worked gives the same
        version. Raises UploadIncomplete, with the file and the part, when something did not arrive as announced."""
        upload = await self._uploads.get(upload_id)
        if (
            upload is not None
            and upload.status == COMPLETED
            and upload.version_id
            and (upload.created_by == actor.user_id or actor.is_admin)
        ):
            version = await self._versions.get_version_by_id(upload.version_id)
            if version is not None:
                return version
        upload, files = await self._open(actor, upload_id)
        dataset = await self._datasets.get(upload.dataset_id)
        assert dataset is not None  # _open found it

        sent = [file for file in files if file.multipart_id is not None]
        received = {file.id: await self._checked_parts(file) for file in sent}  # all checked before anything is joined
        for file in files:
            if file.multipart_id is None and await self._store.head(file.storage_key) is None:  # it was already stored
                raise UploadIncomplete(f"{file.path} is no longer stored in the dataset: send it")
        joined: list[DatasetUploadFile] = []
        try:
            for file in sent:
                await self._store.complete_multipart(file.storage_key, file.multipart_id or "", received[file.id])
                joined.append(file)
                info = await self._store.head(file.storage_key)
                if info is None or info.size != file.size_bytes:
                    raise UploadIncomplete(f"{file.path} is {info.size if info else 0} bytes, not {file.size_bytes}")
            added = [
                DatasetFile(
                    id=file.id,
                    path=file.path,
                    size_bytes=file.size_bytes,
                    # A file that was already stored keeps the fingerprint it was found by; one that was sent has none
                    # until a worker reads it (what the browser announced is not believed).
                    sha256=file.sha256 if file.multipart_id is None else None,
                    content_type=file.content_type,
                    storage_key=file.storage_key,
                    split=None,
                    rows=None,
                    columns=[],
                )
                for file in files
            ]
            version = await self._versions.record(
                actor, dataset, added, list(upload.remove), upload.message, await self._readme(files)
            )
            upload.status, upload.completed_at, upload.version_id = COMPLETED, datetime.now(UTC), version.id
            await self._uploads.commit()
        except Exception:
            for file in joined:  # what was put together is of no use now
                await self._store.delete(file.storage_key)
            await self._abort_all([file for file in sent if file not in joined])
            upload.status = ABORTED
            await self._uploads.commit()
            raise
        await self._jobs.process_version(version.id)  # the files are read by the worker
        return version

    async def _checked_parts(self, file: DatasetUploadFile) -> list[PartInfo]:
        """The parts of a file, if they are all there and the size the browser was told."""
        parts = {part.number: part for part in await self._store.list_parts(file.storage_key, file.multipart_id or "")}
        for number in range(1, file.parts_count + 1):
            expected = (
                file.part_size
                if number < file.parts_count
                else file.size_bytes - file.part_size * (file.parts_count - 1)
            )
            part = parts.get(number)
            if part is None:
                raise UploadIncomplete(f"{file.path}: part {number} is missing")
            if part.size != expected:
                raise UploadIncomplete(f"{file.path}: part {number} has {part.size} bytes, not {expected}")
        return [parts[number] for number in range(1, file.parts_count + 1)]

    async def _readme(self, files: list[DatasetUploadFile]) -> bytes | None:
        """The text of the README, when there is a small one: it becomes the card of the dataset."""
        file = next((f for f in files if f.path == README and f.size_bytes <= README_MAX_BYTES), None)
        stored = await self._store.get(file.storage_key) if file else None
        return stored.data if stored else None

    # ---- giving up

    async def abort(self, actor: Actor, upload_id: uuid.UUID) -> None:
        upload, _ = await self._open(actor, upload_id)
        await self._give_up(upload, ABORTED)

    async def expire_stale(self, now: datetime | None = None) -> int:
        """Gives up the uploads whose time is over, and frees what they had received. Returns how many. This is a job
        for the worker: nobody else comes back to an upload that was abandoned."""
        stale = await self._uploads.open_until(now or datetime.now(UTC))
        for upload in stale:
            await self._give_up(upload, EXPIRED)
        return len(stale)

    async def _give_up(self, upload: DatasetUpload, status: str) -> None:
        await self._abort_all(await self._uploads.files(upload.id))
        upload.status = status
        await self._uploads.commit()

    async def _abort_all(self, files: list[DatasetUploadFile]) -> None:
        for file in files:
            if file.multipart_id is not None:
                await self._store.abort_multipart(file.storage_key, file.multipart_id)
