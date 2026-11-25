"""A dataset, as a program uses it: look at it, change it, download its files or read its rows, make new versions."""

from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from myhug import _plan, _rows
from myhug._download import _signed_address, download
from myhug._models import DatasetMemberOut, DatasetOut, FileOut, VersionOut
from myhug._ranges import RangeFile, ranged
from myhug._transfer import PARALLEL, LocalFile, ProgressCallback, cache_folder
from myhug._upload import Routes, upload
from myhug.client import Client
from myhug.errors import NotFound, UnsupportedFormat, VersionFailed, WaitTimeout


class NoColumnarCopy(Exception):
    """The copy in Parquet of a file is not there (any more): read the file itself."""


DONE = ("ready", "failed")
POLL_SECONDS = 2.0


def split_address(address: str) -> tuple[str, str]:
    owner, _, name = address.partition("/")
    if not owner or not name or "/" in name:
        raise ValueError(f"{address!r} is not an address: it is `owner/name`")
    return owner, name


class Datasets:
    """`client.datasets`: the datasets I can see, one by its address, and a new one."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list(
        self, *, q: str | None = None, owner: str | None = None, modality: str | None = None, sort: str | None = None
    ) -> Iterator[Any]:
        """The datasets I can see, page after page (the next page is asked for when the loop gets there)."""
        from myhug._models import DatasetSummaryOut

        params: dict[str, Any] = {"q": q, "owner": owner, "modality": modality, "sort": sort}
        for item in self._client.paginate("/api/datasets", params):
            yield DatasetSummaryOut.model_validate(item)

    def get(self, address: str) -> "Dataset":
        owner, name = split_address(address)
        return Dataset(
            self._client, DatasetOut.model_validate(self._client.json("GET", f"/api/datasets/{owner}/{name}"))
        )

    def create(self, name: str, *, modality: str, **fields: Any) -> "Dataset":
        """A dataset in my name. More fields: `description`, `language`, `license`, `tags`, `visibility`, `card`."""
        info = self._client.json("POST", "/api/datasets", json={"name": name, "modality": modality, **fields})
        return Dataset(self._client, DatasetOut.model_validate(info))


class Dataset:
    def __init__(self, client: Client, info: DatasetOut) -> None:
        self._client = client
        self.info = info

    def __repr__(self) -> str:
        return f"Dataset({self.address!r})"

    @property
    def address(self) -> str:
        return f"{self.info.owner}/{self.info.name}"

    @property
    def _base(self) -> str:
        return f"/api/datasets/{self.info.owner}/{self.info.name}"

    @property
    def splits(self) -> list[str]:
        return [s.name for s in self.info.splits or []]

    # ---- the dataset itself

    def refresh(self) -> Self:
        self.info = DatasetOut.model_validate(self._client.json("GET", self._base))
        return self

    def update(self, **changes: Any) -> Self:
        """Changes `description`, `language`, `license`, `tags`, `visibility`, `card`: what is not given stays."""
        self.info = DatasetOut.model_validate(self._client.json("PATCH", self._base, json=changes))
        return self

    def delete(self) -> None:
        self._client.json("DELETE", self._base)

    def like(self) -> int:
        """Likes it (doing it again changes nothing), and says how many likes it has."""
        return self._client.json("PUT", f"{self._base}/like")["likes"]

    def unlike(self) -> int:
        return self._client.json("DELETE", f"{self._base}/like")["likes"]

    # ---- who has access besides the creator (for the people who can edit the dataset)

    def members(self) -> list[DatasetMemberOut]:
        return [DatasetMemberOut.model_validate(m) for m in self._client.json("GET", f"{self._base}/members")]

    def set_member(self, user_id: str, role: str) -> DatasetMemberOut:
        """Gives access (`reader`, `annotator`: also annotates, `maintainer`: also changes it), or changes the role."""
        done = self._client.json("PUT", f"{self._base}/members/{user_id}", json={"role": role})
        return DatasetMemberOut.model_validate(done)

    def remove_member(self, user_id: str) -> None:
        self._client.json("DELETE", f"{self._base}/members/{user_id}")

    # ---- versions and files

    def versions(self) -> list[VersionOut]:
        """The versions, the newest first."""
        return [VersionOut.model_validate(v) for v in self._client.json("GET", f"{self._base}/versions")]

    def _latest(self) -> int:
        """The number of the latest version: asked once and then given to every call, so that the files listed and the
        files downloaded are of the same version even if a new one arrives meanwhile."""
        self.refresh()
        if not self.info.version:
            raise ValueError(f"{self.address} has no version yet")
        return self.info.version

    def files(self, *, version: int | None = None, split: str | None = None) -> list[FileOut]:
        """The files of a version (the latest by default), only those of a split if one is given."""
        number = version or self._latest()
        files = [
            FileOut.model_validate(f)
            for f in self._client.json("GET", f"{self._base}/files", params={"version": number})
        ]
        return _plan.select(files, split=split, path=None, known_splits=self.splits) if split else files

    def download(
        self,
        to: str | Path | None = None,
        *,
        version: int | None = None,
        split: str | None = None,
        path: str | None = None,
        progress: ProgressCallback | None = None,
        parallel: int = PARALLEL,
    ) -> list[Path]:
        """Downloads the raw files of a version (the latest by default): all of them, those of a `split`, or one `path`.
        They go under `to` with the path they have in the dataset (by default in the cache of the SDK). A file already
        there, or already on the machine, is not fetched again, and an interrupted download goes on."""
        number = version or self._latest()
        files = self._select(number, split=split, path=path)
        folder = (
            Path(to)
            if to
            else cache_folder(self._client.cache_dir) / "datasets" / self.info.owner / self.info.name / str(number)
        )
        jobs = [(f, _plan.inside(folder, f.path)) for f in files]
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            return list(pool.map(lambda job: self._fetch(number, *job, progress), jobs))

    def _select(self, number: int, *, split: str | None, path: str | None) -> list[FileOut]:
        files = [
            FileOut.model_validate(f)
            for f in self._client.json("GET", f"{self._base}/files", params={"version": number})
        ]
        return _plan.select(files, split=split, path=path, known_splits=self.splits)

    def _fetch(self, number: int, file: FileOut, dest: Path, progress: ProgressCallback | None) -> Path:
        route = f"{self._base}/files/{file.path}"
        return download(
            self._client,
            route,
            dest,
            size=file.size_bytes,
            sha256=file.sha256,
            progress=progress,
            params={"version": number},
        )

    # ---- rows

    def iter_rows(
        self, split: str | None = None, *, version: int | None = None, streaming: bool = False
    ) -> Iterator[dict[str, Any]]:
        """The rows of a split (`train` if there is one, else the first), one dict by row, file after file.

        By default each file is downloaded first (and kept: the next time it is read from disk). With `streaming=True` a
        csv, tsv or jsonl file is read straight from the storage while it arrives and kept nowhere: one pass, nothing
        on disk. A Parquet file is always downloaded (it is read by ranges of the file, not from start to end)."""
        number = version or self._latest()
        chosen = split or ("train" if "train" in self.splits else (self.splits[0] if self.splits else None))
        files = [f for f in self._select(number, split=chosen, path=None) if _rows.is_readable(f.path)]
        if not files:
            raise UnsupportedFormat(
                f"{self.address} has no csv, tsv, jsonl or parquet file{f' in {chosen}' if chosen else ''}"
            )
        for file in files:
            if streaming and file.columnar and _rows.have_pyarrow():
                try:
                    opened = self._open_columnar(number, file)
                except NoColumnarCopy:
                    opened = None  # the copy went away meanwhile: the file itself is still there
                if opened is not None:
                    yield from opened
                    continue
            if streaming and _rows.suffix_of(file.path) != _rows.PARQUET:
                yield from self._stream(number, file)
            else:
                local = self._fetch(number, file, _plan.inside(self._rows_folder(number), file.path), None)
                yield from _rows.file_rows(file.path, str(local))

    def _rows_folder(self, number: int) -> Path:
        return cache_folder(self._client.cache_dir) / "datasets" / self.info.owner / self.info.name / str(number)

    def _open_columnar(self, number: int, file: FileOut) -> Iterator[dict[str, Any]]:
        """The rows of a Parquet file, or of the copy in Parquet the platform made of a table: read by ranges of the
        file, one group of rows at a time, so a file of any size takes the memory of a group and nothing on disk.
        Raises NoColumnarCopy, before any row, when there is no copy to read."""
        route = f"{self._base}/files/{file.path}"
        params = {"version": number, "format": "parquet"}
        try:
            address = _signed_address(self._client.request("GET", route, params=params))
        except NotFound:
            raise NoColumnarCopy from None

        def fetch(start: int, end: int) -> tuple[bytes, int | None]:
            nonlocal address
            for attempt in range(2):
                headers = {"Range": f"bytes={start}-{end - 1}", "Accept-Encoding": "identity"}
                answer = self._client.storage("GET", address, headers=headers)
                if answer.status_code == 403 and attempt == 0:
                    address = _signed_address(self._client.request("GET", route, params=params))  # it expired
                    continue
                return ranged(answer, start, end)
            raise AssertionError("unreachable")  # pragma: no cover

        return _rows.parquet_rows(file.path, RangeFile(fetch))

    def _stream(self, number: int, file: FileOut) -> Iterator[dict[str, Any]]:
        address = _signed_address(
            self._client.request("GET", f"{self._base}/files/{file.path}", params={"version": number})
        )
        parser, lines = _rows.parser_for(file.path), _rows.Lines(file.path)
        with self._client.stream_storage(address, headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code != 200:
                from myhug.errors import ApiError

                raise ApiError(response.status_code, "The storage refused the download")
            for block in response.iter_bytes():
                for line in lines.feed(block):
                    yield from parser.feed(line)
        for line in lines.feed(b"", last=True):
            yield from parser.feed(line)
        yield from parser.finish()

    # ---- new versions

    def new_version(self, *, message: str = "", wait: bool = False, fingerprint: bool = True) -> "VersionBuilder":
        """A new version: `with dataset.new_version("fix") as v: v.add("train.csv"); v.remove("old.csv")`. Nothing
        is sent until the block ends without an error; what is not touched stays as it was in the latest version."""
        return VersionBuilder(self, message=message, wait=wait, fingerprint=fingerprint)

    def upload_file(
        self, source: str | Path, path: str | None = None, *, message: str = "", wait: bool = False
    ) -> VersionOut:
        """Adds (or replaces) one file, which becomes a new version."""
        return self.new_version(message=message, wait=wait).add(source, path).commit()

    def upload_folder(
        self,
        folder: str | Path,
        *,
        prefix: str = "",
        delete: bool = False,
        message: str = "",
        ignore: Sequence[str] = _plan.DEFAULT_IGNORE,
        wait: bool = False,
        progress: ProgressCallback | None = None,
    ) -> VersionOut | None:
        """Makes the dataset hold what a folder holds, by a new version that carries only the difference: what is new or
        changed is sent, what is the same (same fingerprint) is not, and with `delete=True` what the folder no longer
        has is taken out. Nothing changes: no version is made and `None` is returned."""
        local = _plan.walk(Path(folder), ignore=ignore, prefix=prefix)
        remote = self.files() if self.info.version else []
        if prefix:
            remote = [f for f in remote if f.path.startswith(prefix.strip("/") + "/")]
        plan = _plan.plan_folder(local, remote, delete=delete)
        if plan.nothing:
            return None
        with self.new_version(message=message, wait=wait, fingerprint=False) as version:
            version.progress = progress
            for file in plan.send:
                version.add(file.source, file.path, sha256=file.sha256)
            for path in plan.remove:
                version.remove(path)
        return version.result

    def wait(self, version: int | None = None, *, timeout: float = 600.0) -> VersionOut:
        """Waits until the platform has read the files of a version: `ready`, or it raises `VersionFailed`."""
        number = version or self._latest()
        waited = 0.0
        while True:
            found = next((v for v in self.versions() if v.number == number), None)
            if found is not None and found.status in DONE:
                if found.status == "failed":
                    raise VersionFailed(number, found.error)
                return found
            if waited >= timeout:
                raise WaitTimeout(f"Version {number} of {self.address} is still being read after {timeout:.0f} s")
            self._client._sleep(POLL_SECONDS)
            waited += POLL_SECONDS


class VersionBuilder:
    """What goes into a new version: files to add (or replace), paths to take out. A context manager: it is sent
    when the block ends well, dropped when it raises."""

    def __init__(self, dataset: Dataset, *, message: str, wait: bool, fingerprint: bool) -> None:
        self._dataset = dataset
        self._message = message
        self._wait = wait
        self._fingerprint = fingerprint
        self._add: dict[str, LocalFile] = {}
        self._remove: list[str] = []
        self.progress: ProgressCallback | None = None
        self.result: VersionOut | None = None

    def add(self, source: str | Path, path: str | None = None, *, sha256: str | None = None) -> Self:
        """A file, with the path it will have in the dataset (its name by default). The last one added wins."""
        source = Path(source)
        if not source.is_file():
            raise ValueError(f"{source} is not a file")
        remote = _plan.remote_path(path or source.name)
        self._add[remote] = LocalFile(source, remote, sha256=sha256)
        return self

    def add_folder(self, folder: str | Path, *, prefix: str = "", ignore: Sequence[str] = _plan.DEFAULT_IGNORE) -> Self:
        for file in _plan.walk(Path(folder), ignore=ignore, prefix=prefix):
            self._add[file.path] = file
        return self

    def remove(self, path: str) -> Self:
        """Takes a path out of the new version."""
        self._remove.append(_plan.remote_path(path))
        return self

    def commit(self) -> VersionOut:
        if not self._add and not self._remove:
            raise ValueError("Nothing to commit: add a file or remove a path")
        overlap = set(self._add) & set(self._remove)
        if overlap:
            raise ValueError(f"{sorted(overlap)[0]!r} is both added and removed")
        done = upload(
            self._dataset._client,
            Routes(f"{self._dataset._base}/uploads", "/api/uploads"),
            list(self._add.values()),
            message=self._message,
            remove=self._remove,
            fingerprint=self._fingerprint,
            progress=self.progress,
        )
        self._dataset.refresh()
        self.result = VersionOut.model_validate(done)
        if self._wait:
            self.result = self._dataset.wait(self.result.number)
        return self.result

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        if kind is None:
            self.commit()
