"""Sending the files of a version: announce them, send each part straight to the storage (a few at a time, again if it
fails), then complete. What reached the storage is asked of the API, so an upload that was interrupted (a crash, Ctrl-C,
no network) is taken up again from the parts that are there when the same call is made again."""

import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from myhug._transfer import (
    ATTEMPTS,
    PARALLEL,
    FileChangedError,
    LocalFile,
    Progress,
    ProgressCallback,
    cache_folder,
    forget_state,
    load_state,
    missing_parts,
    read_part,
    save_state,
    sha256_of,
    state_dir,
    state_key,
)
from myhug.aclient import AsyncClient
from myhug.client import Client
from myhug.errors import ConnectionFailed, FileChanged, NotFound, UploadError


@dataclass(frozen=True)
class Routes:
    """Where an upload goes. `start` announces it (`/api/datasets/{owner}/{name}/uploads`), `base` is where it is then
    followed (`/api/uploads`, `/api/model-uploads`)."""

    start: str
    base: str


def _announcement(
    files: Sequence[LocalFile], remove: Sequence[str], message: str, extra: dict[str, Any] | None
) -> dict:
    return {
        "files": [{"path": f.path, "size": f.size, "content_type": f.content_type, "sha256": f.sha256} for f in files],
        "remove": list(remove),
        "message": message,
        **(extra or {}),
    }


def _matches(upload: dict, files: Sequence[LocalFile]) -> bool:
    """Whether an upload that is open is the one for these files."""
    wanted = {(f.path, f.size) for f in files}
    return upload["status"] == "open" and {(e["path"], e["size_bytes"]) for e in upload["files"]} == wanted


def _received(entry: dict) -> dict[int, int]:
    return {p["number"]: p["size"] for p in entry.get("received") or []}


def _todo(upload: dict, by_path: dict[str, LocalFile]) -> list[tuple[dict, LocalFile, int]]:
    work = []
    for entry in upload["files"]:
        if entry["already_stored"]:
            continue  # the platform already holds this exact file: nothing to send
        file = by_path[entry["path"]]
        work.extend((entry, file, n) for n in missing_parts(entry, _received(entry)))
    return work


def _total(upload: dict) -> int:
    return sum(e["size_bytes"] for e in upload["files"] if not e["already_stored"])


def _sent_so_far(upload: dict) -> int:
    return sum(sum(_received(e).values()) for e in upload["files"] if not e["already_stored"])


# ---- blocking


def upload(
    client: Client,
    routes: Routes,
    files: Sequence[LocalFile],
    *,
    message: str = "",
    remove: Sequence[str] = (),
    extra: dict[str, Any] | None = None,
    fingerprint: bool = True,
    progress: ProgressCallback | None = None,
    parallel: int = PARALLEL,
) -> Any:
    """Sends the files and returns what `complete` answers (the version). `fingerprint`: compute each file's SHA-256
    first, so that a file the platform already holds is not sent again (it costs one read of each file)."""
    if fingerprint:
        for f in files:
            f.sha256 = f.sha256 or sha256_of(f.source)
    folder = state_dir(cache_folder(client.cache_dir))
    key = state_key(routes.start, list(files), list(remove), message)
    by_path = {f.path: f for f in files}

    upload_id = load_state(folder, key)
    current: dict | None = None
    if upload_id:
        try:
            current = client.json("GET", f"{routes.base}/{upload_id}", params={"parts": "true"})
        except NotFound:
            current = None
        if current is not None and not _matches(current, files):
            current = None
    if current is None:
        forget_state(folder, key)
        current = client.json("POST", routes.start, json=_announcement(files, remove, message, extra))
        save_state(folder, key, current["id"])
        current = client.json("GET", f"{routes.base}/{current['id']}", params={"parts": "true"})
    upload_id = current["id"]

    total, done = _total(current), _sent_so_far(current)
    if progress:
        progress(Progress(done, total))
    try:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            for sent in pool.map(lambda w: _send_part(client, routes, upload_id, *w), _todo(current, by_path)):
                done += sent
                if progress:
                    progress(Progress(done, total))
        result = client.json("POST", f"{routes.base}/{upload_id}/complete", retry=False)
    except FileChangedError as error:
        raise FileChanged(f"{error.path} changed since it was announced: nothing more was sent") from None
    forget_state(folder, key)
    return result


def _send_part(client: Client, routes: Routes, upload_id: str, entry: dict, file: LocalFile, number: int) -> int:
    data = read_part(file, entry, number)
    for attempt in range(ATTEMPTS):
        # An address for each try: the first may have expired.
        signed = client.json(
            "POST", f"{routes.base}/{upload_id}/parts", json={"file_id": entry["id"], "numbers": [number]}, retry=True
        )
        try:
            response = client.storage("PUT", signed["parts"][0]["url"], content=data)
            if response.is_success:
                return len(data)
        except ConnectionFailed:
            pass  # the storage did not answer: another try, with another address
        client._sleep(client._retry.wait(attempt))
    raise UploadError(f"The part {number} of {entry['path']} did not reach the storage: run it again to go on")


def abort(client: Client, routes: Routes, upload_id: str) -> None:
    client.json("DELETE", f"{routes.base}/{upload_id}")


# ---- asyncio


async def aupload(
    client: AsyncClient,
    routes: Routes,
    files: Sequence[LocalFile],
    *,
    message: str = "",
    remove: Sequence[str] = (),
    extra: dict[str, Any] | None = None,
    fingerprint: bool = True,
    progress: ProgressCallback | None = None,
    parallel: int = PARALLEL,
) -> Any:
    if fingerprint:
        for f in files:
            f.sha256 = f.sha256 or await asyncio.to_thread(sha256_of, f.source)
    folder = state_dir(cache_folder(client.cache_dir))
    key = state_key(routes.start, list(files), list(remove), message)
    by_path = {f.path: f for f in files}

    upload_id = load_state(folder, key)
    current: dict | None = None
    if upload_id:
        try:
            current = await client.json("GET", f"{routes.base}/{upload_id}", params={"parts": "true"})
        except NotFound:
            current = None
        if current is not None and not _matches(current, files):
            current = None
    if current is None:
        forget_state(folder, key)
        started = await client.json("POST", routes.start, json=_announcement(files, remove, message, extra))
        save_state(folder, key, started["id"])
        current = await client.json("GET", f"{routes.base}/{started['id']}", params={"parts": "true"})
    upload_id = current["id"]

    total, done = _total(current), _sent_so_far(current)
    if progress:
        progress(Progress(done, total))
    gate = asyncio.Semaphore(max(1, parallel))

    async def one(entry: dict, file: LocalFile, number: int) -> int:
        async with gate:
            return await _asend_part(client, routes, upload_id, entry, file, number)

    try:
        tasks = [asyncio.create_task(one(*w)) for w in _todo(current, by_path)]
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
        result = await client.json("POST", f"{routes.base}/{upload_id}/complete", retry=False)
    except FileChangedError as error:
        raise FileChanged(f"{error.path} changed since it was announced: nothing more was sent") from None
    forget_state(folder, key)
    return result


async def _asend_part(
    client: AsyncClient, routes: Routes, upload_id: str, entry: dict, file: LocalFile, number: int
) -> int:
    data = await asyncio.to_thread(read_part, file, entry, number)
    for attempt in range(ATTEMPTS):
        signed = await client.json(
            "POST", f"{routes.base}/{upload_id}/parts", json={"file_id": entry["id"], "numbers": [number]}, retry=True
        )
        try:
            response = await client.storage("PUT", signed["parts"][0]["url"], content=data)
            if response.is_success:
                return len(data)
        except ConnectionFailed:
            pass
        await client._sleep(client._retry.wait(attempt))
    raise UploadError(f"The part {number} of {entry['path']} did not reach the storage: run it again to go on")


async def aabort(client: AsyncClient, routes: Routes, upload_id: str) -> None:
    await client.json("DELETE", f"{routes.base}/{upload_id}")


__all__ = ["Routes", "aabort", "abort", "aupload", "upload"]
