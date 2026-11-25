"""Calls written once for the blocking and the asyncio resources."""

import asyncio
from typing import Any

from tests.conftest import Driver


async def get(d: Driver, kind: str, address: str) -> Any:
    resources = d.client.datasets if kind == "datasets" else d.client.models
    if d.mode == "sync":
        return await asyncio.to_thread(resources.get, address)
    return await resources.get(address)


async def run(d: Driver, call: Any, *args: Any, **kwargs: Any) -> Any:
    """`call(*args)` of a blocking resource (in a thread) or of an asyncio one (awaited)."""
    if d.mode == "sync":
        return await asyncio.to_thread(call, *args, **kwargs)
    return await call(*args, **kwargs)


async def collect(d: Driver, make: Any) -> list[Any]:
    """The items of a generator (blocking: read in a thread, asyncio: `async for`)."""
    if d.mode == "sync":
        return await asyncio.to_thread(lambda: list(make()))
    return [item async for item in make()]


async def commit(
    d: Driver, resource: Any, adds: dict[str, Any] | None = None, removes: tuple[str, ...] = (), **options: Any
) -> Any:
    """A new version through the builder, as a block that ends well."""

    def build() -> Any:
        return resource.new_version(**options)

    if d.mode == "sync":

        def blocking() -> Any:
            with build() as version:
                for path, source in (adds or {}).items():
                    version.add(source, path)
                for path in removes:
                    version.remove(path)
            return version.result

        return await asyncio.to_thread(blocking)
    async with build() as version:
        for path, source in (adds or {}).items():
            version.add(source, path)
        for path in removes:
            version.remove(path)
    return version.result
