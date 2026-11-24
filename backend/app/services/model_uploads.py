import math
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models import ModelFile, ModelUpload, ModelUploadFile, ModelVersion
from app.models.model_upload import ABORTED, COMPLETED, EXPIRED, OPEN
from app.repositories.model_uploads import ModelUploadRepository
from app.repositories.models import ModelRepository
from app.services.actor import Actor
from app.services.code_reference import CodeReference
from app.services.dataset_uploads import PlannedFile, part_size_for
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
from app.services.model_access import ModelAccess
from app.services.model_versions import ModelVersionService, new_file
from app.services.paths import clean_path
from app.storage import ObjectStore, PartInfo


@dataclass(frozen=True)
class ModelUploadView:
    upload: ModelUpload
    files: list[ModelUploadFile]
    # What reached the storage so far, by file: only when asked (it is a call to the storage for each file).
    received: dict[uuid.UUID, list[PartInfo]] | None = None


class ModelUploadService:
    """Sending the files of a model, straight from the browser to the storage, in parts: the same contract as the
    uploads of the datasets (`start`, the signed `part_urls`, `get` to resume, `complete`, `abort`, and an expiry for
    the ones that are abandoned).

    It is a copy of that service and not a generalisation of it on purpose: the two differ in what surrounds the upload
    (here a registration in MLflow and a link to the code, there the README and the reading of the rows), and sharing
    one service would put a condition for each in every method. What really is common (the size of the parts, the
    paths, the planned file) is imported."""

    def __init__(
        self,
        models: ModelRepository,
        uploads: ModelUploadRepository,
        versions: ModelVersionService,
        access: ModelAccess,
        store: ObjectStore,
        *,
        max_bytes: int,
        max_files: int,
        part_bytes: int,
        session: timedelta,
        signed_seconds: int,
    ) -> None:
        self._models = models
        self._uploads = uploads
        self._versions = versions
        self._access = access
        self._store = store
        self._max_bytes = max_bytes
        self._max_files = max_files
        self._part_bytes = part_bytes
        self._session = session
        self._signed_seconds = signed_seconds

    # ---- starting

    async def start(
        self,
        actor: Actor,
        owner: str,
        name: str,
        *,
        files: list[PlannedFile],
        remove: list[str],
        message: str,
        code: dict | None,
    ) -> ModelUploadView:
        """Announces the files. Raises what is wrong with them (path, size, number, code) before anything is made."""
        model = await self._access.get_editable(actor, owner, name)
        checked = self._versions.check_code(code)
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
        await self._versions.plan(model, paths, remove)  # the paths to remove must be there, and the total is checked

        upload = ModelUpload(
            id=uuid.uuid4(),
            model_id=model.id,
            remove=[clean_path(path) for path in remove],
            message=message,
            code=checked.as_dict() if checked else None,
            created_by=actor.user_id,
            created_by_username=actor.username,
            expires_at=datetime.now(UTC) + self._session,
        )
        prepared: list[ModelUploadFile] = []
        try:
            for path, planned in zip(paths, files, strict=True):
                file_id = uuid.uuid4()
                content_type = planned.content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
                stored = (
                    await self._versions.find_stored(model, planned.sha256, planned.size) if planned.sha256 else None
                )
                if stored is not None:
                    # The model already holds this file: the new path points to the same object, nothing is sent.
                    row = ModelUploadFile(
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
                    key = new_file(model.id, file_id)
                    size = part_size_for(planned.size, self._part_bytes)
                    row = ModelUploadFile(
                        id=file_id,
                        upload_id=upload.id,
                        path=path,
                        size_bytes=planned.size,
                        content_type=content_type,
                        storage_key=key,
                        sha256=planned.sha256,
                        multipart_id=await self._store.create_multipart(key, content_type),
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
        return ModelUploadView(upload, prepared)

    # ---- during

    async def _open(self, actor: Actor, upload_id: uuid.UUID) -> tuple[ModelUpload, list[ModelUploadFile]]:
        """An upload of this person, still open. Raises UploadNotFound (not theirs), UploadClosed, and the errors of a
        model they can no longer change."""
        upload = await self._uploads.get(upload_id)
        if upload is None or not (upload.created_by == actor.user_id or actor.is_admin):
            raise UploadNotFound
        model = await self._models.get(upload.model_id)
        if model is None:
            raise UploadNotFound
        await self._access.require_editable(actor, model)
        if upload.status == OPEN and upload.expires_at <= datetime.now(UTC):
            await self._give_up(upload, EXPIRED)
        if upload.status != OPEN:
            raise UploadClosed
        return upload, await self._uploads.files(upload.id)

    async def get(self, actor: Actor, upload_id: uuid.UUID, *, parts: bool = False) -> ModelUploadView:
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
        return ModelUploadView(upload, files, received)

    async def part_urls(
        self, actor: Actor, upload_id: uuid.UUID, file_id: uuid.UUID, numbers: list[int]
    ) -> list[tuple[int, str]]:
        """The signed addresses to which the browser sends these parts of a file."""
        _, files = await self._open(actor, upload_id)
        file = next((f for f in files if f.id == file_id), None)
        if file is None:
            raise UploadNotFound
        if file.multipart_id is None:
            raise UploadIncomplete(f"{file.path} is already stored in the model: there is nothing to send")
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

    async def complete(self, actor: Actor, upload_id: uuid.UUID) -> ModelVersion:
        """Puts the parts of every file together, makes the version and registers it in MLflow. Playing it again after
        it worked gives the same version. Raises UploadIncomplete, with the file and the part, when something did not
        arrive as announced. If MLflow does not answer nothing is left: the objects are deleted, the upload is over."""
        upload = await self._uploads.get(upload_id)
        if (
            upload is not None
            and upload.status == COMPLETED
            and upload.version_id
            and (upload.created_by == actor.user_id or actor.is_admin)
        ):
            known = await self._versions.get_by_id(upload.version_id)
            if known is not None:
                return known
        upload, files = await self._open(actor, upload_id)
        model = await self._models.get(upload.model_id)
        assert model is not None  # _open found it

        sent = [file for file in files if file.multipart_id is not None]
        received = {file.id: await self._checked_parts(file) for file in sent}  # all checked before anything is joined
        for file in files:
            if file.multipart_id is None and await self._store.head(file.storage_key) is None:  # it was already stored
                raise UploadIncomplete(f"{file.path} is no longer stored in the model: send it")
        # Plain values: the rows are expired when the transaction is rolled back, and the clean-up needs these then.
        pending = {file.storage_key: file.multipart_id or "" for file in sent}
        joined: list[str] = []
        try:
            for file in sent:
                await self._store.complete_multipart(file.storage_key, file.multipart_id or "", received[file.id])
                joined.append(file.storage_key)
                info = await self._store.head(file.storage_key)
                if info is None or info.size != file.size_bytes:
                    raise UploadIncomplete(f"{file.path} is {info.size if info else 0} bytes, not {file.size_bytes}")
            added = [
                ModelFile(
                    id=file.id,
                    path=file.path,
                    size_bytes=file.size_bytes,
                    # A file that was already stored keeps the fingerprint it was found by; one that was sent has none
                    # until a worker reads it (what the browser announced is not believed).
                    sha256=file.sha256 if file.multipart_id is None else None,
                    content_type=file.content_type,
                    storage_key=file.storage_key,
                )
                for file in files
            ]
            code = CodeReference.from_dict(upload.code) if upload.code else None
            version = await self._versions.record(actor, model, added, list(upload.remove), upload.message, code)
            upload.status, upload.completed_at, upload.version_id = COMPLETED, datetime.now(UTC), version.id
            await self._uploads.commit()
        except Exception:
            await self._uploads.rollback()
            for key in joined:  # what was put together is of no use now
                await self._store.delete(key)
            for key, multipart_id in pending.items():
                if key not in joined:
                    await self._store.abort_multipart(key, multipart_id)
            failed = await self._uploads.get(upload_id)
            if failed is not None:
                failed.status = ABORTED
                await self._uploads.commit()
            raise
        return version

    async def _checked_parts(self, file: ModelUploadFile) -> list[PartInfo]:
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

    # ---- giving up

    async def abort(self, actor: Actor, upload_id: uuid.UUID) -> None:
        upload, _ = await self._open(actor, upload_id)
        await self._give_up(upload, ABORTED)

    async def expire_stale(self, now: datetime | None = None) -> int:
        """Gives up the uploads whose time is over, and frees what they had received. Returns how many."""
        stale = await self._uploads.open_until(now or datetime.now(UTC))
        for upload in stale:
            await self._give_up(upload, EXPIRED)
        return len(stale)

    async def _give_up(self, upload: ModelUpload, status: str) -> None:
        await self._abort_all(await self._uploads.files(upload.id))
        upload.status = status
        await self._uploads.commit()

    async def _abort_all(self, files: list[ModelUploadFile]) -> None:
        for file in files:
            if file.multipart_id is not None:
                await self._store.abort_multipart(file.storage_key, file.multipart_id)
