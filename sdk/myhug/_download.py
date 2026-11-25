"""Downloading a file: the API answers with a signed address, the bytes come from the storage, in a stream, onto disk.

An interrupted download goes on from where it stopped (`Range`), a file is checked against its size and fingerprint
before it is kept, and a file the machine already holds (same fingerprint) is not fetched again."""

import asyncio
from pathlib import Path

import httpx2

from myhug._transfer import ATTEMPTS, Cache, Progress, ProgressCallback, cache_folder, sha256_of
from myhug.aclient import AsyncClient
from myhug.client import Client
from myhug.errors import ApiError, ConnectionFailed, IntegrityError


def _already_there(dest: Path, size: int | None, sha256: str | None) -> bool:
    if not dest.is_file() or (size is not None and dest.stat().st_size != size):
        return False
    if sha256 is not None:
        return sha256_of(dest) == sha256
    return size is not None  # without a fingerprint, the same size is all there is to go by


def _check(part: Path, size: int | None, sha256: str | None) -> None:
    """Keeps nothing that is not what the platform holds."""
    if (size is not None and part.stat().st_size != size) or (sha256 is not None and sha256_of(part) != sha256):
        part.unlink(missing_ok=True)
        raise IntegrityError("What was downloaded is not the file the platform holds: it was not kept")


def _start(part: Path, size: int | None) -> int:
    """Where to go on from: what is on disk, unless it is more than the file (a leftover of another one)."""
    have = part.stat().st_size if part.exists() else 0
    if size is not None and have > size:
        part.unlink()
        return 0
    return have


def _signed_address(response: httpx2.Response) -> str:
    location = response.headers.get("location")
    if response.status_code not in (301, 302, 303, 307, 308) or not location:
        raise ApiError(response.status_code, "The API did not give an address to download from")
    return location


def download(
    client: Client,
    route: str,
    dest: str | Path,
    *,
    size: int | None = None,
    sha256: str | None = None,
    progress: ProgressCallback | None = None,
    params: dict | None = None,
) -> Path:
    """Downloads what `route` (an API path of a file) serves to `dest`. `size` and `sha256`, when known, are checked."""
    target = Path(dest)
    cache = Cache(cache_folder(client.cache_dir))
    if _already_there(target, size, sha256):
        return target
    if sha256 and cache.has(sha256):
        cache.give(sha256, target)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    for attempt in range(ATTEMPTS + 1):
        address = _signed_address(client.request("GET", route, params=params))  # a fresh address each time: they expire
        have = _start(part, size)
        headers = {"Accept-Encoding": "identity", **({"Range": f"bytes={have}-"} if have else {})}
        try:
            with client.stream_storage(address, headers=headers) as response:
                if response.status_code == 416 and size is not None and have == size:
                    break  # it was all there already
                if response.status_code not in (200, 206):
                    if attempt < ATTEMPTS and response.status_code in (403, 429, 500, 502, 503, 504):
                        client._sleep(client._retry.wait(attempt))
                        continue
                    raise ApiError(response.status_code, "The storage refused the download")
                if response.status_code == 200:
                    have = 0  # it does not do ranges: from the beginning
                total = size if size is not None else (int(response.headers.get("content-length", 0)) + have or 0)
                done = have
                with part.open("ab" if have else "wb") as out:
                    for block in response.iter_bytes():
                        out.write(block)
                        done += len(block)
                        if progress:
                            progress(Progress(done, total, str(target)))
            break
        except httpx2.TransportError:
            if attempt == ATTEMPTS:
                raise ConnectionFailed("The download was interrupted: run it again to go on") from None
            client._sleep(client._retry.wait(attempt))
    _check(part, size, sha256)
    part.replace(target)
    if sha256:
        cache.add(target, sha256)
    return target


async def adownload(
    client: AsyncClient,
    route: str,
    dest: str | Path,
    *,
    size: int | None = None,
    sha256: str | None = None,
    progress: ProgressCallback | None = None,
    params: dict | None = None,
) -> Path:
    target = Path(dest)
    cache = Cache(cache_folder(client.cache_dir))
    if await asyncio.to_thread(_already_there, target, size, sha256):
        return target
    if sha256 and cache.has(sha256):
        cache.give(sha256, target)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    for attempt in range(ATTEMPTS + 1):
        address = _signed_address(await client.request("GET", route, params=params))
        have = _start(part, size)
        headers = {"Accept-Encoding": "identity", **({"Range": f"bytes={have}-"} if have else {})}
        try:
            async with client.stream_storage(address, headers=headers) as response:
                if response.status_code == 416 and size is not None and have == size:
                    break
                if response.status_code not in (200, 206):
                    if attempt < ATTEMPTS and response.status_code in (403, 429, 500, 502, 503, 504):
                        await client._sleep(client._retry.wait(attempt))
                        continue
                    raise ApiError(response.status_code, "The storage refused the download")
                if response.status_code == 200:
                    have = 0
                total = size if size is not None else (int(response.headers.get("content-length", 0)) + have or 0)
                done = have
                with part.open("ab" if have else "wb") as out:
                    async for block in response.aiter_bytes():
                        out.write(block)
                        done += len(block)
                        if progress:
                            progress(Progress(done, total, str(target)))
            break
        except httpx2.TransportError:
            if attempt == ATTEMPTS:
                raise ConnectionFailed("The download was interrupted: run it again to go on") from None
            await client._sleep(client._retry.wait(attempt))
    await asyncio.to_thread(_check, part, size, sha256)
    part.replace(target)
    if sha256:
        cache.add(target, sha256)
    return target
