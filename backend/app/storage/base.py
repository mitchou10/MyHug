from collections.abc import AsyncIterator
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ObjectNotFound(Exception):  # noqa: N818 - says what it is, like KeyError
    """The object that was asked for is not in the storage."""


class StoredObject(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: bytes
    content_type: str


class ObjectInfo(BaseModel):
    """What the storage says about an object without giving it."""

    model_config = ConfigDict(frozen=True)

    size: int
    content_type: str


class PartInfo(BaseModel):
    """A part of a file uploaded in parts: its number (from 1), its size and the fingerprint the storage gave it."""

    model_config = ConfigDict(frozen=True)

    number: int
    size: int
    etag: str


class ObjectStore(Protocol):
    """What the services need from an object storage. Nothing here is specific to S3."""

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> StoredObject | None:
        """The object, or None when it does not exist."""
        ...

    async def delete(self, key: str) -> None: ...

    def stream(self, key: str, chunk_size: int = 8 * 1024 * 1024) -> AsyncIterator[bytes]:
        """The content of an object as it comes, in chunks: a large file is never held whole in memory.
        Raises ObjectNotFound when the object does not exist."""
        ...

    async def head(self, key: str) -> ObjectInfo | None:
        """The size and the type of an object, or None when it does not exist."""
        ...

    # ---- a large file goes in parts, each one sent by the browser to its own signed address

    async def create_multipart(self, key: str, content_type: str) -> str:
        """Starts the upload of a file in parts and returns its identifier."""
        ...

    async def presign_part(self, key: str, upload_id: str, number: int, expires_in: int) -> str:
        """The address to which the browser sends one part (with PUT). It is signed, and stops working after
        `expires_in` seconds."""
        ...

    async def list_parts(self, key: str, upload_id: str) -> list[PartInfo]:
        """The parts that arrived so far, by number: what is needed to resume an upload."""
        ...

    async def complete_multipart(self, key: str, upload_id: str, parts: list[PartInfo]) -> None:
        """Puts the parts together: the object exists from then on."""
        ...

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        """Gives up an upload and frees the parts that arrived. Does nothing when it is already gone."""
        ...

    async def presign_get(self, key: str, expires_in: int, filename: str | None = None) -> str:
        """The address from which the browser downloads an object, signed and short-lived."""
        ...
