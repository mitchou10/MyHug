import json
import logging
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime

from app.jobs import Jobs, NoJobs
from app.models import Model, ModelFile, ModelVersion
from app.models.model_version import FAILED, PENDING, READY, UNRESOLVED
from app.registry import MlflowLinks, ModelRegistry, registered_name
from app.registry.compensation import registered_model, registered_run, registered_version
from app.repositories.model_versions import ModelVersionRepository
from app.repositories.models import ModelRepository
from app.services.actor import Actor
from app.services.code_reference import CodeReference, check_code_reference
from app.services.errors import (
    EmptyVersion,
    InvalidFilePath,
    ModelFileNotFound,
    ModelVersionNotFound,
    RegistryConflict,
    TooManyFiles,
    VersionFailed,
)
from app.services.model_access import EDITORS, ModelAccess
from app.services.paths import clean_path
from app.storage import ObjectStore

logger = logging.getLogger(__name__)
MANIFEST = "MANIFEST.json"


@dataclass(frozen=True)
class VersionView:
    """A version with what depends on who looks at it."""

    version: ModelVersion
    # Where to see it in MLflow: only for who can edit the model, and only for a version MLflow knows.
    mlflow_url: str | None = None


def new_file(model_id: uuid.UUID, file_id: uuid.UUID) -> str:
    """Where the content of a file of a model is in the storage. The id is the one of the file, so two uploads never
    meet; a file that does not change from one version to the next keeps its key."""
    return f"models/{model_id}/files/{file_id}"


def manifest_of(model: Model, number: int, message: str, files: list[ModelFile], code: CodeReference | None) -> bytes:
    """What MLflow is given of a version: the list of its files, so that its page says what the version holds. The
    weights themselves stay in the storage of the platform."""
    return json.dumps(
        {
            "model": f"{model.owner}/{model.name}",
            "version": number,
            "message": message,
            "files": [{"path": f.path, "size": f.size_bytes, "sha256": f.sha256} for f in files],
            "code": code.as_dict() if code else None,
        },
        indent=2,
        sort_keys=True,
    ).encode()


class ModelVersionService:
    """The versions of a model: make one (files, a link to the code, or both), list, read, download and delete them.

    A version is a snapshot: the files of the previous one, with some added or replaced and some taken out. Its code is
    written on it and is not inherited."""

    def __init__(
        self,
        models: ModelRepository,
        versions: ModelVersionRepository,
        access: ModelAccess,
        registry: ModelRegistry,
        links: MlflowLinks,
        store: ObjectStore,
        *,
        max_files: int,
        signed_seconds: int,
        code_hosts: list[str],
        jobs: Jobs | None = None,
    ) -> None:
        self._models = models
        self._versions = versions
        self._access = access
        self._registry = registry
        self._links = links
        self._store = store
        self._max_files = max_files
        self._signed_seconds = signed_seconds
        self._code_hosts = code_hosts
        self._jobs: Jobs = jobs or NoJobs()

    def check_code(self, code: dict | None) -> CodeReference | None:
        """The code reference of a request, checked. Raises InvalidCodeReference."""
        if not code:
            return None
        return check_code_reference(
            code.get("url") or "",
            ref=code.get("ref"),
            ref_kind=code.get("ref_kind"),
            path=code.get("path"),
            entrypoint=code.get("entrypoint"),
            hosts=self._code_hosts,
        )

    # ---- making a version

    async def create_code_version(
        self, actor: Actor, owner: str, name: str, *, code: dict | None, message: str
    ) -> ModelVersion:
        """A version that is only a link to the code (the files of the previous version are kept). It is made by a plain
        request: there is nothing to upload. Raises InvalidCodeReference, EmptyVersion if there is no code."""
        model = await self._access.get_editable(actor, owner, name)
        checked = self.check_code(code)
        if checked is None:
            raise EmptyVersion
        return await self.record(actor, model, [], [], message, checked)

    async def plan(
        self, model: Model, paths: list[str], remove: list[str]
    ) -> tuple[ModelVersion | None, list[ModelFile]]:
        """The latest version, and the files of it that the next one keeps: not the ones taken out, not the ones that
        are replaced. Raises ModelFileNotFound for a path to remove that is not there, and TooManyFiles."""
        previous = await self._versions.latest(model.id)
        before = await self._versions.files(previous.id) if previous else []
        removed = {clean_path(path) for path in remove}
        if missing := sorted(removed - {file.path for file in before}):
            raise ModelFileNotFound(f"Cannot remove {missing[0]}: it is not in the model")
        replaced = set(paths)
        kept = [file for file in before if file.path not in removed and file.path not in replaced]
        if len(kept) + len(paths) > self._max_files:
            raise TooManyFiles
        return previous, kept

    async def get_by_id(self, version_id: uuid.UUID) -> ModelVersion | None:
        return await self._versions.get_by_id(version_id)

    async def find_stored(self, model: Model, sha256: str, size: int) -> ModelFile | None:
        return await self._versions.find_stored(model.id, sha256, size)

    async def record(
        self,
        actor: Actor,
        model: Model,
        added: list[ModelFile],
        remove: list[str],
        message: str,
        code: CodeReference | None,
    ) -> ModelVersion:
        """Makes the version from files that are already in the storage (the kept ones of the previous version and
        `added`), registers it in MLflow, and commits. MLflow first and the database last: if the database fails, what
        was made in MLflow is taken back. The caller takes the new objects back if this raises.

        Raises EmptyVersion when the version would hold neither a file nor a code reference."""
        await self._models.lock(model.id)  # one version at a time per model: the numbers follow each other
        _, kept = await self.plan(model, [file.path for file in added], remove)
        files = [*kept, *added]
        if not files and code is None:
            raise EmptyVersion
        number = await self._versions.next_number(model.id)
        version = ModelVersion(
            id=uuid.uuid4(),
            model_id=model.id,
            number=number,
            # A file nobody fingerprinted yet is read by a worker; a version without one has nothing to wait for.
            status=PENDING if any(file.sha256 is None for file in files) else READY,
            message=message,
            size_bytes=sum(file.size_bytes for file in files),
            created_by=actor.user_id,
            created_by_username=actor.username,
        )
        if code is not None:
            version.code_url, version.code_ref, version.code_ref_kind = code.url, code.ref, code.ref_kind
            version.code_path, version.entrypoint, version.code_state = code.path, code.entrypoint, UNRESOLVED
        rows = [
            ModelFile(
                id=file.id if file in added else uuid.uuid4(),
                path=file.path,
                size_bytes=file.size_bytes,
                sha256=file.sha256,
                content_type=file.content_type,
                storage_key=file.storage_key,
            )
            for file in files
        ]
        async with AsyncExitStack() as undo:
            if files:
                await self._register(undo, model, version, number, message, rows, code)
            try:
                self._versions.add(version)
                await self._versions.flush()
                for row in rows:
                    row.version_id = version.id
                    self._versions.add_file(row)
                model.version, model.size_bytes, model.updated_at = number, version.size_bytes, datetime.now(UTC)
                await self._versions.commit()
            except Exception:
                await self._versions.rollback()
                raise
        # Queued once the version is recorded, so that the worker finds it.
        if version.status == PENDING:
            await self._jobs.process_model_version(version.id)  # the files are fingerprinted by the worker
        if code is not None:
            await self._jobs.resolve_code(version.id)  # the reference is pinned to a commit
        return version

    async def _register(
        self,
        undo: AsyncExitStack,
        model: Model,
        version: ModelVersion,
        number: int,
        message: str,
        files: list[ModelFile],
        code: CodeReference | None,
    ) -> None:
        """Makes the registered model if MLflow does not know it yet, a run holding the manifest, and the version. What
        is made is taken back (by `undo`) if the block it is in raises."""
        registered = registered_name(model.owner, model.name)
        if not await self._registry.model_exists(registered):
            try:
                await undo.enter_async_context(registered_model(self._registry, registered))
            except RegistryConflict:
                pass  # another request made it at the same time
        run = await undo.enter_async_context(registered_run(self._registry, registered))
        await self._registry.log_artifact(run, MANIFEST, manifest_of(model, number, message, files, code))
        remote = await undo.enter_async_context(registered_version(self._registry, registered, run))
        version.mlflow_name, version.mlflow_version, version.mlflow_run_id = registered, remote.version, run.run_id

    # ---- reading

    def _view(self, version: ModelVersion, role: str | None) -> VersionView:
        url = None
        if role in EDITORS and version.mlflow_name and version.mlflow_version:
            url = self._links.version(version.mlflow_name, version.mlflow_version)
        return VersionView(version, url)

    async def _version_of(self, model: Model, number: int | None) -> ModelVersion:
        version = await (self._versions.latest(model.id) if number is None else self._versions.get(model.id, number))
        if version is None:
            raise ModelVersionNotFound
        return version

    async def view_of(self, actor: Actor, version: ModelVersion) -> VersionView:
        """A version of a model the person can see, as they see it."""
        model = await self._models.get(version.model_id)
        assert model is not None  # a version always has its model
        _, role = await self._access.get_readable_model(actor, model)
        return self._view(version, role)

    async def history(self, actor: Actor, owner: str, name: str) -> list[VersionView]:
        model, role = await self._access.get_readable(actor, owner, name)
        return [self._view(version, role) for version in await self._versions.history(model.id)]

    async def get(self, actor: Actor, owner: str, name: str, number: int | None) -> tuple[VersionView, list[ModelFile]]:
        """A version (the latest by default) and its files."""
        model, role = await self._access.get_readable(actor, owner, name)
        version = await self._version_of(model, number)
        return self._view(version, role), await self._versions.files(version.id)

    async def download(self, actor: Actor, owner: str, name: str, path: str, number: int | None) -> str:
        """The signed address from which to download a file: it goes from the storage to the browser, not through the
        API. Counts a download. A version whose files did not pass the checks is not given."""
        model, _ = await self._access.get_readable(actor, owner, name)
        version = await self._version_of(model, number)
        if version.status == FAILED:
            raise VersionFailed
        try:
            clean = clean_path(path)
        except InvalidFilePath:
            raise ModelFileNotFound from None
        file = await self._versions.file(version.id, clean)
        if file is None or await self._store.head(file.storage_key) is None:
            raise ModelFileNotFound
        await self._versions.count_downloads(model.id)
        await self._versions.commit()
        return await self._store.presign_get(file.storage_key, self._signed_seconds, file.path.rsplit("/", 1)[-1])

    # ---- deleting

    async def delete(self, actor: Actor, owner: str, name: str, number: int) -> None:
        """Deletes a version: in MLflow first, then here. The files that another version still holds are kept. If MLflow
        does not answer nothing is deleted, and it can be done again."""
        model = await self._access.get_editable(actor, owner, name)
        version = await self._version_of(model, number)
        keys = await self._versions.keys_of(version.id)
        kept = await self._versions.keys_kept_by_others(model.id, version.id, keys)
        if version.mlflow_name and version.mlflow_version:
            await self._registry.delete_version(version.mlflow_name, version.mlflow_version)
        await self._versions.delete(version.id)
        await self._versions.set_latest(model.id)
        await self._versions.commit()
        if gone := sorted(keys - kept):
            await self._store.delete_many(gone)
