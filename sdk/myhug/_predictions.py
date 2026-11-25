"""Sending the predictions of an evaluation: the file goes straight to the storage in parts (the ones that are not
there yet, again if one fails), then the platform is told it is complete and a worker computes the metrics."""

import asyncio
import json
import uuid
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from myhug._transfer import (
    ATTEMPTS,
    PARALLEL,
    FileChangedError,
    LocalFile,
    Progress,
    ProgressCallback,
    cache_folder,
    missing_parts,
    read_part,
)
from myhug.aclient import AsyncClient
from myhug.client import Client
from myhug.errors import ConnectionFailed, FileChanged, UploadError

FORMATS = {".jsonl": "jsonl", ".ndjson": "jsonl", ".csv": "csv", ".parquet": "parquet"}


def format_of(path: Path) -> str:
    try:
        return FORMATS[path.suffix.lower()]
    except KeyError:
        raise ValueError(f"The predictions are a .jsonl, .csv or .parquet file, not {path.name!r}") from None


class Prepared:
    """The file of predictions: the one that was given, or one written from a list (and removed afterwards)."""

    def __init__(self, path: Path, format: str, temporary: bool) -> None:
        self.path, self.format, self.temporary = path, format, temporary

    def __enter__(self) -> "Prepared":
        return self

    def __exit__(self, *exc: object) -> None:
        if self.temporary:
            self.path.unlink(missing_ok=True)


def prepare(predictions: str | Path | Iterable[Any], *, folder: Path | None, column: str) -> Prepared:
    """A path is used as it is. A list is written as JSON lines, one line for each item of the split in order: a
    value is the prediction (`{column: value}`), an object is the line."""
    if isinstance(predictions, str | Path):
        path = Path(predictions)
        if not path.is_file():
            raise ValueError(f"{path} is not a file")
        return Prepared(path, format_of(path), False)
    target = cache_folder(folder) / "predictions"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = target / f"{uuid.uuid4().hex}.jsonl"
    try:
        with path.open("w") as out:
            count = 0
            for item in predictions:
                line = item if isinstance(item, dict) else {column: item}
                out.write(json.dumps(line, allow_nan=False) + "\n")
                count += 1
    except ValueError as error:
        path.unlink(missing_ok=True)
        raise ValueError(f"A prediction cannot be written (nan and infinity are not JSON): {error}") from None
    if not count:
        path.unlink(missing_ok=True)
        raise ValueError("There is no prediction to send")
    return Prepared(path, "jsonl", True)


def _announced(state: dict, file: LocalFile, path: Path) -> None:
    """The file must be the one the evaluation was started with: the size that was announced."""
    if state.get("size_bytes") != file.size:
        raise FileChanged(
            f"{path.name} is not the file the evaluation was started with ({state.get('size_bytes')} bytes)"
        )


def _entry(state: dict, size: int, name: str) -> dict:
    return {"size_bytes": size, "part_size": state["part_size"], "parts_count": state["parts_count"], "path": name}


def _received(state: dict) -> dict[int, int]:
    return {p["number"]: p["size"] for p in state.get("received") or []}


# ---- blocking


def send(
    client: Client,
    base: str,
    path: Path,
    *,
    progress: ProgressCallback | None = None,
    parallel: int = PARALLEL,
) -> Any:
    """Sends what is missing of the file to `base` (an evaluation) and says it is complete: returns the evaluation."""
    state = client.json("GET", f"{base}/upload", params={"parts": "true"})
    file = LocalFile(path, path.name)
    _announced(state, file, path)
    entry = _entry(state, file.size, path.name)
    todo = missing_parts(entry, _received(state))
    total = file.size
    done = total - sum(min(entry["part_size"], total - (n - 1) * entry["part_size"]) for n in todo)
    if progress:
        progress(Progress(done, total))
    try:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            sizes = pool.map(lambda n: _send_part(client, base, file, entry, n), todo)
            for sent in sizes:
                done += sent
                if progress:
                    progress(Progress(done, total))
    except FileChangedError:
        raise FileChanged(f"{path.name} changed since the evaluation was started: nothing more was sent") from None
    return client.json("POST", f"{base}/upload/complete", retry=False)


def _send_part(client: Client, base: str, file: LocalFile, entry: dict, number: int) -> int:
    data = read_part(file, entry, number)
    for attempt in range(ATTEMPTS):
        signed = client.json("POST", f"{base}/upload/parts", json={"numbers": [number]}, retry=True)
        try:
            if client.storage("PUT", signed["parts"][0]["url"], content=data).is_success:
                return len(data)
        except ConnectionFailed:
            pass
        client._sleep(client._retry.wait(attempt))
    raise UploadError(f"The part {number} of the predictions did not reach the storage: send them again to go on")


# ---- asyncio


async def asend(
    client: AsyncClient,
    base: str,
    path: Path,
    *,
    progress: ProgressCallback | None = None,
    parallel: int = PARALLEL,
) -> Any:
    state = await client.json("GET", f"{base}/upload", params={"parts": "true"})
    file = await asyncio.to_thread(LocalFile, path, path.name)
    _announced(state, file, path)
    entry = _entry(state, file.size, path.name)
    todo = missing_parts(entry, _received(state))
    total = file.size
    done = total - sum(min(entry["part_size"], total - (n - 1) * entry["part_size"]) for n in todo)
    if progress:
        progress(Progress(done, total))
    gate = asyncio.Semaphore(max(1, parallel))

    async def one(number: int) -> int:
        async with gate:
            return await _asend_part(client, base, file, entry, number)

    try:
        tasks = [asyncio.create_task(one(n)) for n in todo]
        try:
            for finished in asyncio.as_completed(tasks):
                done += await finished
                if progress:
                    progress(Progress(done, total))
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    except FileChangedError:
        raise FileChanged(f"{path.name} changed since the evaluation was started: nothing more was sent") from None
    return await client.json("POST", f"{base}/upload/complete", retry=False)


async def _asend_part(client: AsyncClient, base: str, file: LocalFile, entry: dict, number: int) -> int:
    data = await asyncio.to_thread(read_part, file, entry, number)
    for attempt in range(ATTEMPTS):
        signed = await client.json("POST", f"{base}/upload/parts", json={"numbers": [number]}, retry=True)
        try:
            if (await client.storage("PUT", signed["parts"][0]["url"], content=data)).is_success:
                return len(data)
        except ConnectionFailed:
            pass
        await client._sleep(client._retry.wait(attempt))
    raise UploadError(f"The part {number} of the predictions did not reach the storage: send them again to go on")
