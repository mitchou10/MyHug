"""The same as `datasets.py`, for asyncio."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from myhug import _plan, _rows
from myhug._download import _signed_address, adownload
from myhug._models import DatasetMemberOut, DatasetOut, DatasetSummaryOut, FileOut, VersionOut
from myhug._ranges import RangeFile, ranged
from myhug._transfer import PARALLEL, LocalFile, ProgressCallback, cache_folder
from myhug._upload import Routes, aupload
from myhug.aclient import AsyncClient
from myhug.datasets import DONE, POLL_SECONDS, NoColumnarCopy, split_address
from myhug.errors import ApiError, NotFound, UnsupportedFormat, VersionFailed, WaitTimeout


class AsyncDatasets:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list(
        self, *, q: str | None = None, owner: str | None = None, modality: str | None = None, sort: str | None = None
    ) -> AsyncIterator[DatasetSummaryOut]:
        params: dict[str, Any] = {"q": q, "owner": owner, "modality": modality, "sort": sort}
        async for item in self._client.paginate("/api/datasets", params):
            yield DatasetSummaryOut.model_validate(item)

    async def get(self, address: str) -> "AsyncDataset":
        owner, name = split_address(address)
        info = await self._client.json("GET", f"/api/datasets/{owner}/{name}")
        return AsyncDataset(self._client, DatasetOut.model_validate(info))

    async def create(self, name: str, *, modality: str, **fields: Any) -> "AsyncDataset":
        info = await self._client.json("POST", "/api/datasets", json={"name": name, "modality": modality, **fields})
        return AsyncDataset(self._client, DatasetOut.model_validate(info))


class AsyncDataset:
    def __init__(self, client: AsyncClient, info: DatasetOut) -> None:
        self._client = client
        self.info = info

    def __repr__(self) -> str:
        return f"AsyncDataset({self.address!r})"

    @property
    def address(self) -> str:
        return f"{self.info.owner}/{self.info.name}"

    @property
    def _base(self) -> str:
        return f"/api/datasets/{self.info.owner}/{self.info.name}"

    @property
    def splits(self) -> list[str]:
        return [s.name for s in self.info.splits or []]

    async def refresh(self) -> Self:
        self.info = DatasetOut.model_validate(await self._client.json("GET", self._base))
        return self

    async def update(self, **changes: Any) -> Self:
        self.info = DatasetOut.model_validate(await self._client.json("PATCH", self._base, json=changes))
        return self

    async def delete(self) -> None:
        await self._client.json("DELETE", self._base)

    async def like(self) -> int:
        return (await self._client.json("PUT", f"{self._base}/like"))["likes"]

    async def unlike(self) -> int:
        return (await self._client.json("DELETE", f"{self._base}/like"))["likes"]

    async def members(self) -> list[DatasetMemberOut]:
        return [DatasetMemberOut.model_validate(m) for m in await self._client.json("GET", f"{self._base}/members")]

    async def set_member(self, user_id: str, role: str) -> DatasetMemberOut:
        done = await self._client.json("PUT", f"{self._base}/members/{user_id}", json={"role": role})
        return DatasetMemberOut.model_validate(done)

    async def remove_member(self, user_id: str) -> None:
        await self._client.json("DELETE", f"{self._base}/members/{user_id}")

    async def versions(self) -> list[VersionOut]:
        return [VersionOut.model_validate(v) for v in await self._client.json("GET", f"{self._base}/versions")]

    async def _latest(self) -> int:
        await self.refresh()
        if not self.info.version:
            raise ValueError(f"{self.address} has no version yet")
        return self.info.version

    async def _select(self, number: int, *, split: str | None, path: str | None) -> list[FileOut]:
        raw = await self._client.json("GET", f"{self._base}/files", params={"version": number})
        files = [FileOut.model_validate(f) for f in raw]
        return _plan.select(files, split=split, path=path, known_splits=self.splits)

    async def files(self, *, version: int | None = None, split: str | None = None) -> list[FileOut]:
        number = version or await self._latest()
        return await self._select(number, split=split, path=None)

    def _folder(self, number: int) -> Path:
        return cache_folder(self._client.cache_dir) / "datasets" / self.info.owner / self.info.name / str(number)

    async def _fetch(self, number: int, file: FileOut, dest: Path, progress: ProgressCallback | None) -> Path:
        return await adownload(
            self._client,
            f"{self._base}/files/{file.path}",
            dest,
            size=file.size_bytes,
            sha256=file.sha256,
            progress=progress,
            params={"version": number},
        )

    async def download(
        self,
        to: str | Path | None = None,
        *,
        version: int | None = None,
        split: str | None = None,
        path: str | None = None,
        progress: ProgressCallback | None = None,
        parallel: int = PARALLEL,
    ) -> list[Path]:
        number = version or await self._latest()
        files = await self._select(number, split=split, path=path)
        folder = Path(to) if to else self._folder(number)
        gate = asyncio.Semaphore(max(1, parallel))

        async def one(file: FileOut) -> Path:
            async with gate:
                return await self._fetch(number, file, _plan.inside(folder, file.path), progress)

        return list(await asyncio.gather(*(one(f) for f in files)))

    async def iter_rows(
        self, split: str | None = None, *, version: int | None = None, streaming: bool = False
    ) -> AsyncIterator[dict[str, Any]]:
        number = version or await self._latest()
        chosen = split or ("train" if "train" in self.splits else (self.splits[0] if self.splits else None))
        files = [f for f in await self._select(number, split=chosen, path=None) if _rows.is_readable(f.path)]
        if not files:
            raise UnsupportedFormat(
                f"{self.address} has no csv, tsv, jsonl or parquet file{f' in {chosen}' if chosen else ''}"
            )
        for file in files:
            if streaming and file.columnar and _rows.have_pyarrow():
                try:
                    opened = await self._open_columnar(number, file)
                except NoColumnarCopy:
                    opened = None  # the copy went away meanwhile: the file itself is still there
                if opened is not None:
                    async for row in opened:
                        yield row
                    continue
            if streaming and _rows.suffix_of(file.path) != _rows.PARQUET:
                async for row in self._stream(number, file):
                    yield row
            else:
                local = await self._fetch(number, file, _plan.inside(self._folder(number), file.path), None)
                async for row in _rows.abatches(_rows.file_rows(file.path, str(local))):
                    yield row

    async def _open_columnar(self, number: int, file: FileOut) -> AsyncIterator[dict[str, Any]]:
        """The same as the blocking one: the file is read by ranges in a thread, and each range is fetched by the event
        loop, which stays free meanwhile. Raises NoColumnarCopy, before any row, when there is no copy to read."""
        route = f"{self._base}/files/{file.path}"
        params = {"version": number, "format": "parquet"}
        try:
            address = _signed_address(await self._client.request("GET", route, params=params))
        except NotFound:
            raise NoColumnarCopy from None
        loop = asyncio.get_running_loop()

        async def afetch(start: int, end: int) -> tuple[bytes, int | None]:
            nonlocal address
            for attempt in range(2):
                headers = {"Range": f"bytes={start}-{end - 1}", "Accept-Encoding": "identity"}
                answer = await self._client.storage("GET", address, headers=headers)
                if answer.status_code == 403 and attempt == 0:
                    address = _signed_address(await self._client.request("GET", route, params=params))  # it expired
                    continue
                return ranged(answer, start, end)
            raise AssertionError("unreachable")  # pragma: no cover

        def fetch(start: int, end: int) -> tuple[bytes, int | None]:
            return asyncio.run_coroutine_threadsafe(afetch(start, end), loop).result()

        handle = await asyncio.to_thread(RangeFile, fetch)
        return _rows.abatches(_rows.parquet_rows(file.path, handle))

    async def _stream(self, number: int, file: FileOut) -> AsyncIterator[dict[str, Any]]:
        route = f"{self._base}/files/{file.path}"
        address = _signed_address(await self._client.request("GET", route, params={"version": number}))
        parser, lines = _rows.parser_for(file.path), _rows.Lines(file.path)
        async with self._client.stream_storage(address, headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code != 200:
                raise ApiError(response.status_code, "The storage refused the download")
            async for block in response.aiter_bytes():
                for line in lines.feed(block):
                    for row in parser.feed(line):
                        yield row
        for line in lines.feed(b"", last=True):
            for row in parser.feed(line):
                yield row
        for row in parser.finish():
            yield row

    def new_version(self, *, message: str = "", wait: bool = False, fingerprint: bool = True) -> "AsyncVersionBuilder":
        """`async with dataset.new_version("fix labels") as v: v.add("train.csv"); v.remove("old.csv")`."""
        return AsyncVersionBuilder(self, message=message, wait=wait, fingerprint=fingerprint)

    async def upload_file(
        self, source: str | Path, path: str | None = None, *, message: str = "", wait: bool = False
    ) -> VersionOut:
        return await self.new_version(message=message, wait=wait).add(source, path).commit()

    async def upload_folder(
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
        local = await asyncio.to_thread(_plan.walk, Path(folder), ignore=ignore, prefix=prefix)
        remote = await self.files() if self.info.version else []
        if prefix:
            remote = [f for f in remote if f.path.startswith(prefix.strip("/") + "/")]
        plan = await asyncio.to_thread(_plan.plan_folder, local, remote, delete=delete)
        if plan.nothing:
            return None
        async with self.new_version(message=message, wait=wait, fingerprint=False) as version:
            version.progress = progress
            for file in plan.send:
                version.add(file.source, file.path, sha256=file.sha256)
            for path in plan.remove:
                version.remove(path)
        return version.result

    async def wait(self, version: int | None = None, *, timeout: float = 600.0) -> VersionOut:
        number = version or await self._latest()
        waited = 0.0
        while True:
            found = next((v for v in await self.versions() if v.number == number), None)
            if found is not None and found.status in DONE:
                if found.status == "failed":
                    raise VersionFailed(number, found.error)
                return found
            if waited >= timeout:
                raise WaitTimeout(f"Version {number} of {self.address} is still being read after {timeout:.0f} s")
            await self._client._sleep(POLL_SECONDS)
            waited += POLL_SECONDS


class AsyncVersionBuilder:
    def __init__(self, dataset: AsyncDataset, *, message: str, wait: bool, fingerprint: bool) -> None:
        self._dataset = dataset
        self._message = message
        self._wait = wait
        self._fingerprint = fingerprint
        self._add: dict[str, LocalFile] = {}
        self._remove: list[str] = []
        self.progress: ProgressCallback | None = None
        self.result: VersionOut | None = None

    def add(self, source: str | Path, path: str | None = None, *, sha256: str | None = None) -> Self:
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
        self._remove.append(_plan.remote_path(path))
        return self

    async def commit(self) -> VersionOut:
        if not self._add and not self._remove:
            raise ValueError("Nothing to commit: add a file or remove a path")
        overlap = set(self._add) & set(self._remove)
        if overlap:
            raise ValueError(f"{sorted(overlap)[0]!r} is both added and removed")
        done = await aupload(
            self._dataset._client,
            Routes(f"{self._dataset._base}/uploads", "/api/uploads"),
            list(self._add.values()),
            message=self._message,
            remove=self._remove,
            fingerprint=self._fingerprint,
            progress=self.progress,
        )
        await self._dataset.refresh()
        self.result = VersionOut.model_validate(done)
        if self._wait:
            self.result = await self._dataset.wait(self.result.number)
        return self.result

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        if kind is None:
            await self.commit()
