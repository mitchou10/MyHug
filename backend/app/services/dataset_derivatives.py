import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models import DatasetFile, DatasetFileDerivative
from app.models.dataset_derivative import CONVERTER, FAILED, PARQUET, PROCESSING, READY
from app.repositories.dataset_derivatives import DatasetDerivativeRepository
from app.services import tables
from app.services.errors import DerivativeNotFound, NotBeingProcessed
from app.storage import ObjectStore, PartInfo

logger = logging.getLogger(__name__)
GRACE = timedelta(minutes=2)
PARQUET_TYPE = "application/vnd.apache.parquet"


def params_hash() -> str:
    """What a copy was made with. The same source, made the same way, is the same copy."""
    return hashlib.sha256(f"{PARQUET}:{CONVERTER}".encode()).hexdigest()


@dataclass(frozen=True)
class ToConvert:
    """What the worker needs to make a copy: where the source is (a signed address), what it is and how big, and the
    size of the parts to send the copy in."""

    id: uuid.UUID
    source_url: str
    source_path: str
    source_size_bytes: int
    part_bytes: int


class DatasetDerivatives:
    """The copies of the tabular files in Parquet. The worker reads the source and writes the copy straight to the
    storage in parts; the API keeps the records, checks that the copy has as many rows as the source, and says when it
    can be read (the preview reads it instead of the whole csv or jsonl)."""

    def __init__(
        self,
        derivatives: DatasetDerivativeRepository,
        store: ObjectStore,
        *,
        min_bytes: int,
        max_bytes: int,
        part_bytes: int,
        max_attempts: int = 3,
        stale: timedelta = timedelta(minutes=30),
        signed_seconds: int = 3600,
    ) -> None:
        self._derivatives = derivatives
        self._store = store
        self._min_bytes = min_bytes
        self._max_bytes = max_bytes
        self._part_bytes = part_bytes
        self._max_attempts = max_attempts
        self._stale = stale
        self._signed_seconds = signed_seconds

    def wanted(self, files: list[DatasetFile]) -> list[tuple[str, str, int]]:
        """The files of a version that deserve a copy: tabular, read, and big enough (and not too big)."""
        found: dict[str, tuple[str, str, int]] = {}
        for file in files:
            if tables.is_convertible(file.path) and file.rows and self._min_bytes <= file.size_bytes <= self._max_bytes:
                found.setdefault(file.storage_key, (file.storage_key, file.path, file.size_bytes))
        return list(found.values())

    async def create_for(self, files: list[DatasetFile]) -> list[uuid.UUID]:
        """Makes the copies that are missing. Does not commit: the caller does, then queues the jobs."""
        return await self._derivatives.create_missing(self.wanted(files), params_hash())

    # ---- reading

    async def ready_for(self, keys: list[str]) -> dict[str, DatasetFileDerivative]:
        return await self._derivatives.ready_for(keys, params_hash())

    # ---- for the worker

    async def claim(self, derivative_id: uuid.UUID) -> ToConvert | None:
        """Takes a copy in hand. None when it is not up for the taking (made, taken by another worker, unknown, or given
        up after too many attempts)."""
        derivative = await self._derivatives.claim(derivative_id, datetime.now(UTC) - self._stale)
        if derivative is None:
            return None
        if derivative.attempts > self._max_attempts:
            await self._give_up(derivative, "The copy was interrupted too many times")
            return None
        key = f"derived/{PARQUET}/{derivative.params_hash[:16]}/{derivative.source_storage_key}.parquet"
        if derivative.multipart_id:  # a worker that died left its parts
            await self._store.abort_multipart(derivative.storage_key or key, derivative.multipart_id)
        derivative.storage_key = key
        derivative.multipart_id = await self._store.create_multipart(key, PARQUET_TYPE)
        await self._derivatives.commit()
        return ToConvert(
            id=derivative.id,
            source_url=await self._store.presign_get(
                derivative.source_storage_key, self._signed_seconds, internal=True
            ),
            source_path=derivative.source_path,
            source_size_bytes=derivative.source_size_bytes,
            part_bytes=self._part_bytes,
        )

    async def part_urls(self, derivative_id: uuid.UUID, numbers: list[int]) -> dict[int, str]:
        derivative = await self._held(derivative_id)
        assert derivative.storage_key and derivative.multipart_id  # set when it was claimed
        return {
            number: await self._store.presign_part(
                derivative.storage_key, derivative.multipart_id, number, self._signed_seconds, internal=True
            )
            for number in numbers
        }

    async def complete(
        self, derivative_id: uuid.UUID, rows: int, columns: list[tables.Column]
    ) -> DatasetFileDerivative:
        """Puts the parts together and checks the copy: as many rows as the source. A copy that is not the same marks
        the copy `failed`, never the version: everything keeps working from the original."""
        derivative = await self._held(derivative_id)
        assert derivative.storage_key and derivative.multipart_id
        expected = await self._derivatives.source_rows(derivative.source_storage_key)
        parts = [
            PartInfo(number=p.number, size=p.size, etag=p.etag)
            for p in await self._store.list_parts(derivative.storage_key, derivative.multipart_id)
        ]
        if not parts:
            return await self._give_up(derivative, "The worker sent no part")
        await self._store.complete_multipart(derivative.storage_key, derivative.multipart_id, parts)
        derivative.multipart_id = None
        info = await self._store.head(derivative.storage_key)
        if info is None:
            return await self._give_up(derivative, "The copy is not in the storage")
        if expected is not None and rows != expected:
            await self._store.delete(derivative.storage_key)
            return await self._give_up(derivative, f"The copy has {rows} rows, the file has {expected}")
        derivative.status, derivative.error = READY, None
        derivative.rows, derivative.size_bytes = rows, info.size
        derivative.columns = [{"name": c.name, "dtype": c.dtype} for c in columns]
        await self._derivatives.commit()
        return derivative

    async def fail(self, derivative_id: uuid.UUID, error: str) -> DatasetFileDerivative:
        derivative = await self._held(derivative_id)
        if derivative.multipart_id and derivative.storage_key:
            await self._store.abort_multipart(derivative.storage_key, derivative.multipart_id)
        return await self._give_up(derivative, error[:2000])

    async def release(self, derivative_id: uuid.UUID) -> None:
        await self._derivatives.release(derivative_id)

    async def waiting(self, limit: int = 100) -> list[uuid.UUID]:
        now = datetime.now(UTC)
        return await self._derivatives.waiting(older_than=now - GRACE, stale_before=now - self._stale, limit=limit)

    async def _held(self, derivative_id: uuid.UUID) -> DatasetFileDerivative:
        derivative = await self._derivatives.get_by_id(derivative_id)
        if derivative is None:
            raise DerivativeNotFound
        if derivative.status != PROCESSING:
            raise NotBeingProcessed
        return derivative

    async def _give_up(self, derivative: DatasetFileDerivative, error: str) -> DatasetFileDerivative:
        logger.warning("The copy of %s failed: %s", derivative.source_path, error)
        derivative.status, derivative.error, derivative.multipart_id = FAILED, error, None
        await self._derivatives.commit()
        return derivative
