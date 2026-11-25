import hashlib
import logging
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from typing import Any

from pydantic import BaseModel

from app.jobs import Jobs, NoJobs
from app.models import Dataset, DatasetFile, DatasetFileDerivative, DatasetVersion
from app.models.dataset_version import READY
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services import parquet_pages, tables
from app.services.actor import Actor
from app.services.dataset_access import DatasetAccess
from app.services.dataset_derivatives import DatasetDerivatives
from app.services.errors import (
    DatasetFileNotFound,
    FileTooLarge,
    InvalidFilePath,
    NoParquetCopy,
    NothingToCommit,
    SplitNotFound,
    TooManyFiles,
    VersionNotFound,
    VersionNotReady,
)
from app.services.paths import clean_path
from app.storage import ObjectStore

logger = logging.getLogger(__name__)
README = "README.md"
SPLIT_ORDER = ("train", "validation", "test")
MEDIA = ("image/", "audio/", "video/")
mimetypes.add_type("application/vnd.apache.parquet", ".parquet")
mimetypes.add_type("application/x-ndjson", ".jsonl")
mimetypes.add_type("application/x-ndjson", ".ndjson")


class NamedUpload(BaseModel):
    """A file of a request, read, and where it goes in the dataset."""

    path: str
    data: bytes


@dataclass(frozen=True)
class SplitInfo:
    name: str
    rows: int
    files: int


@dataclass(frozen=True)
class RowsPage:
    split: str
    splits: list[str]
    columns: list[tables.Column]
    rows: list[list[Any]]
    total: int


def splits_of(files: list[DatasetFile]) -> list[SplitInfo]:
    """The parts of a dataset, from its files that hold rows: train first, then validation and test, then the others."""
    found: dict[str, list[DatasetFile]] = {}
    for file in files:
        if file.split is not None:
            found.setdefault(file.split, []).append(file)
    ordered = sorted(
        found, key=lambda name: (SPLIT_ORDER.index(name) if name in SPLIT_ORDER else len(SPLIT_ORDER), name)
    )
    return [SplitInfo(name, sum(f.rows or 0 for f in found[name]), len(found[name])) for name in ordered]


class DatasetVersionService:
    """The files of a dataset: add or remove some (a new version), list and download them, read their rows."""

    def __init__(
        self,
        datasets: DatasetRepository,
        versions: DatasetVersionRepository,
        access: DatasetAccess,
        store: ObjectStore,
        *,
        max_bytes: int,
        max_files: int,
        signed_seconds: int,
        jobs: Jobs | None = None,
        derivatives: DatasetDerivatives | None = None,
    ) -> None:
        self._datasets = datasets
        self._versions = versions
        self._access = access
        self._store = store
        self._max_bytes = max_bytes
        self._max_files = max_files
        self._signed_seconds = signed_seconds
        self._jobs: Jobs = jobs or NoJobs()
        self._derivatives = derivatives

    # ---- writing

    async def create(
        self, actor: Actor, owner: str, name: str, *, uploads: list[NamedUpload], remove: list[str], message: str
    ) -> DatasetVersion:
        """A new version: the files of the previous one, with `uploads` added (or replacing the same path) and the
        `remove` paths taken out. The version is `pending`: a worker reads the files afterwards. Raises the errors of
        the paths and the sizes; nothing is stored if one of them fails."""
        dataset = await self._access.get_editable(actor, owner, name)
        if not uploads and not remove:
            raise NothingToCommit
        paths = [clean_path(upload.path) for upload in uploads]
        if len(set(paths)) != len(paths) or len(paths) > self._max_files:
            raise TooManyFiles if len(paths) > self._max_files else InvalidFilePath
        if any(len(upload.data) > self._max_bytes for upload in uploads):
            raise FileTooLarge

        await self.plan(dataset, paths, remove)  # everything that can be refused, before anything is stored

        added = [
            self._describe(dataset.id, path, upload.data) for path, upload in zip(paths, uploads, strict=True)
        ]  # all checked first
        existing_keys = await self._versions.storage_keys(dataset.id)
        new_keys = {file.storage_key for file, _ in added} - existing_keys
        try:
            for file, data in added:
                if file.storage_key in new_keys:
                    await self._store.put(file.storage_key, data, file.content_type)
            readme = next((data for file, data in added if file.path == README), None)
            version = await self.record(actor, dataset, [file for file, _ in added], remove, message, readme)
        except Exception:
            for key in new_keys:  # nothing points to them
                await self._store.delete(key)
            raise
        await self._jobs.process_version(version.id)  # the files are read by the worker
        return version

    async def plan(
        self, dataset: Dataset, paths: list[str], remove: list[str]
    ) -> tuple[DatasetVersion | None, list[DatasetFile]]:
        """The latest version, and the files of it that the next one keeps: not the ones taken out, not the ones that
        are replaced. Raises DatasetFileNotFound for a path to remove that is not there, and TooManyFiles."""
        previous = await self._versions.latest(dataset.id)
        before = await self._versions.files(previous.id) if previous else []
        removed = {clean_path(path) for path in remove}
        if missing := sorted(removed - {file.path for file in before}):
            raise DatasetFileNotFound(f"Cannot remove {missing[0]}: it is not in the dataset")
        kept = [file for file in before if file.path not in removed and file.path not in set(paths)]
        if len(kept) + len(paths) > self._max_files:
            raise TooManyFiles
        return previous, kept

    async def find_stored(self, dataset: Dataset, sha256: str, size: int) -> DatasetFile | None:
        """The file of this dataset that is exactly this one, if there is one: no need to send it again."""
        return await self._versions.find_stored(dataset.id, sha256, size)

    async def get_version_by_id(self, version_id: uuid.UUID) -> DatasetVersion | None:
        return await self._versions.get_by_id(version_id)

    async def record(
        self,
        actor: Actor,
        dataset: Dataset,
        added: list[DatasetFile],
        remove: list[str],
        message: str,
        readme: bytes | None,
    ) -> DatasetVersion:
        """Makes the version from files that are already in the storage: the ones of the previous version that are
        kept, and `added`. Commits. The caller takes the new objects back if this raises."""
        previous, kept = await self.plan(dataset, [file.path for file in added], remove)
        version = await self._write(actor, dataset, previous, message, kept, added)
        if readme is not None:
            dataset.card = readme.decode("utf-8", errors="replace")
        await self._versions.commit()
        return version

    @staticmethod
    def _describe(dataset_id: uuid.UUID, path: str, data: bytes) -> tuple[DatasetFile, bytes]:
        digest = hashlib.sha256(data).hexdigest()
        file = DatasetFile(
            id=uuid.uuid4(),
            path=path,
            size_bytes=len(data),
            sha256=digest,
            # By its fingerprint: a file that did not change, or that is there twice, is stored once.
            storage_key=f"datasets/{dataset_id}/{digest}",
            split=None,
            rows=None,
            columns=[],
            content_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
        )
        # What is inside is not read here: a worker does it (see DatasetProcessor), so that sending files stays fast.
        return file, data

    async def _write(
        self,
        actor: Actor,
        dataset: Dataset,
        previous: DatasetVersion | None,
        message: str,
        kept: list[DatasetFile],
        added: list[DatasetFile],
    ) -> DatasetVersion:
        version = DatasetVersion(
            id=uuid.uuid4(),
            dataset_id=dataset.id,
            number=(previous.number if previous else 0) + 1,
            message=message,
            created_by=actor.user_id,
            created_by_username=actor.username,
        )
        self._versions.add(version)
        await self._versions.flush()
        files = [*kept, *added]
        for file in files:
            copy = DatasetFile(
                id=uuid.uuid4(),
                version_id=version.id,
                path=file.path,
                size_bytes=file.size_bytes,
                sha256=file.sha256,
                content_type=file.content_type,
                split=file.split,
                rows=file.rows,
                columns=file.columns,
                storage_key=file.storage_key,
            )
            self._versions.add_file(copy)
        # Only what is known without reading the files: how big they are. The rows, the columns and the parts come when
        # the version is ready; a file that did not change keeps what was found in it, so the worker skips it.
        version.size_bytes = sum(f.size_bytes for f in files)
        dataset.version, dataset.rows, dataset.size_bytes = version.number, None, version.size_bytes
        dataset.updated_at = datetime.now(UTC)
        return version

    # ---- reading

    async def _version_of(self, dataset: Dataset, number: int | None) -> DatasetVersion:
        version = await (
            self._versions.latest(dataset.id) if number is None else self._versions.get(dataset.id, number)
        )
        if version is None:
            raise VersionNotFound
        return version

    async def history(self, actor: Actor, owner: str, name: str) -> list[DatasetVersion]:
        dataset, _ = await self._access.get_readable(actor, owner, name)
        return await self._versions.history(dataset.id)

    async def files(
        self, actor: Actor, owner: str, name: str, number: int | None
    ) -> tuple[DatasetVersion, list[DatasetFile]]:
        dataset, _ = await self._access.get_readable(actor, owner, name)
        version = await self._version_of(dataset, number)
        return version, await self._versions.files(version.id)

    async def download(self, actor: Actor, owner: str, name: str, path: str, number: int | None) -> str:
        """The signed address from which to download a file: a large file goes from the storage to the browser, not
        through the API. Counts a download."""
        dataset, _ = await self._access.get_readable(actor, owner, name)
        version = await self._version_of(dataset, number)
        file = await self._versions.file(version.id, clean_path(path))
        if file is None or await self._store.head(file.storage_key) is None:
            raise DatasetFileNotFound
        await self._versions.count_downloads(dataset.id)
        await self._versions.commit()
        return await self._store.presign_get(file.storage_key, self._signed_seconds, file.path.rsplit("/", 1)[-1])

    async def columnar(self, files: list[DatasetFile]) -> set[str]:
        """The paths of the files that can be read by ranges as Parquet: a Parquet file itself, or a table whose copy is
        ready (the copy is a cache made by the system, see the derivatives)."""
        copies = await self._copies([f for f in files if tables.suffix_of(f.path) != tables.PARQUET])
        return {
            f.path
            for f in files
            if tables.suffix_of(f.path) == tables.PARQUET or self._usable(copies.get(f.storage_key)) is not None
        }

    @staticmethod
    def _usable(copy: DatasetFileDerivative | None) -> str | None:
        return copy.storage_key if copy is not None and copy.storage_key and copy.size_bytes else None

    async def download_parquet(self, actor: Actor, owner: str, name: str, path: str, number: int | None) -> str:
        """The signed address of a file as Parquet, to read it by ranges: the file itself if it is one, else the copy
        the system made of it. NoParquetCopy when there is none ready. A copy is a cache: it is not a download."""
        dataset, _ = await self._access.get_readable(actor, owner, name)
        version = await self._version_of(dataset, number)
        file = await self._versions.file(version.id, clean_path(path))
        if file is None:
            raise DatasetFileNotFound
        key = file.storage_key
        if tables.suffix_of(file.path) != tables.PARQUET:
            key = self._usable((await self._copies([file])).get(file.storage_key)) or ""
        if not key or await self._store.head(key) is None:
            raise NoParquetCopy
        return await self._store.presign_get(key, self._signed_seconds)

    async def rows(
        self,
        actor: Actor,
        owner: str,
        name: str,
        *,
        split: str | None,
        number: int | None,
        offset: int,
        limit: int,
        query: str | None,
    ) -> RowsPage:
        """A page of the rows of one split (the preview of a dataset). `query` keeps the rows that contain it."""
        dataset, _ = await self._access.get_readable(actor, owner, name)
        version = await self._version_of(dataset, number)
        if version.status != READY:  # the parts and the columns are found by the worker
            raise VersionNotReady
        files = await self._versions.files(version.id)
        splits = [info.name for info in splits_of(files)]
        if not splits:
            return RowsPage(split="", splits=[], columns=[], rows=[], total=0)
        chosen = split or splits[0]
        if chosen not in splits:
            raise SplitNotFound
        parts = [file for file in files if file.split == chosen]
        columns = [tables.Column(c["name"], c["dtype"]) for c in parts[0].columns]
        copies = await self._copies(parts)  # the Parquet copies of the big files: read by ranges, not whole

        if query:
            needle = query.lower()
            found: list[list[Any]] = []
            for file in parts:
                found.extend(await self._matching(file, copies, needle))
            return RowsPage(chosen, splits, columns, found[offset : offset + limit], len(found))

        page: list[list[Any]] = []
        skipped = 0
        for file in parts:
            count = file.rows or 0
            if skipped + count <= offset:  # the whole file is before the page
                skipped += count
                continue
            start = max(0, offset - skipped)
            page.extend(await self._page(file, copies, start, limit - len(page)))
            skipped += count
            if len(page) >= limit:
                break
        return RowsPage(chosen, splits, columns, page, sum(f.rows or 0 for f in parts))

    async def _copies(self, parts: list[DatasetFile]) -> dict[str, DatasetFileDerivative]:
        if self._derivatives is None:
            return {}
        return await self._derivatives.ready_for([file.storage_key for file in parts])

    async def _page(
        self, file: DatasetFile, copies: dict[str, DatasetFileDerivative], start: int, count: int
    ) -> list[list[Any]]:
        copy = copies.get(file.storage_key)
        if copy is not None and copy.storage_key and copy.size_bytes:
            try:
                return await parquet_pages.page(self._store, copy.storage_key, copy.size_bytes, start, count)
            except Exception:  # a copy is only a faster way: the original is still there
                logger.exception("The copy of %s cannot be read: reading the file itself", file.path)
        return list(islice([row async for row in self._rows_of(file)], start, start + count))

    async def _matching(
        self, file: DatasetFile, copies: dict[str, DatasetFileDerivative], needle: str
    ) -> list[list[Any]]:
        copy = copies.get(file.storage_key)
        if copy is not None and copy.storage_key and copy.size_bytes:
            try:
                return await parquet_pages.matching(self._store, copy.storage_key, copy.size_bytes, needle)
            except Exception:
                logger.exception("The copy of %s cannot be read: reading the file itself", file.path)
        return [
            row
            async for row in self._rows_of(file)
            if any(needle in str(cell).lower() for cell in row if cell is not None)
        ]

    async def _rows_of(self, file: DatasetFile):
        stored = await self._store.get(file.storage_key)
        if stored is None:
            raise DatasetFileNotFound
        for row in tables.iter_rows(file.path, stored.data):
            yield row


def splits_index(split: str | None) -> int:
    return SPLIT_ORDER.index(split) if split in SPLIT_ORDER else len(SPLIT_ORDER)
