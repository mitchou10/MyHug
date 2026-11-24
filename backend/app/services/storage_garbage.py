import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.repositories.storage_references import StorageReferenceRepository
from app.storage import ListedObject, ObjectStore

logger = logging.getLogger(__name__)
# The only places the collector walks. The bucket holds other things (avatars, attachments, the artifacts of MLflow...)
# that it must never touch: a key outside these is never listed, and asking for it is a mistake of the code.
PREFIXES = ("datasets/", "derived/", "models/")
CHECKED_KEYS_SHOWN = 20


@dataclass
class Collected:
    """What a collection found, and what it did about it."""

    dry_run: bool
    busy: bool = False
    scanned: int = 0
    garbage_objects: int = 0
    garbage_bytes: int = 0
    deleted_objects: int = 0
    orphan_copies: int = 0
    started_uploads_given_up: int = 0
    missing_objects: int = 0
    missing_keys: list[str] = field(default_factory=list)
    next_after: str | None = None


class StorageGarbage:
    """Finds the objects of the storage that nothing points to, and deletes them.

    The database is the source of truth: an object is garbage when no file of any version, no upload that is still
    going on and no copy points to its key. It is looked for **by reference** and not by dataset (a key can be shared),
    and only in `PREFIXES`.

    Nothing recent is touched. An object is put in the storage **before** the row that points to it is committed, so a
    young object that nothing points to is normal: only the ones older than `grace` are garbage, and `grace` is longer
    than the longest upload.

    It can be played again and can be stopped anywhere: `collect` does a bounded amount of work and says where to go on
    from. With `dry_run` nothing is deleted: it only says what would be."""

    def __init__(
        self,
        references: StorageReferenceRepository,
        store: ObjectStore,
        *,
        grace: timedelta,
        batch: int = 500,
        max_scanned: int = 20_000,
        max_deletions: int = 5_000,
        check_rows: int = 200,
    ) -> None:
        self._references = references
        self._store = store
        self._grace = grace
        self._batch = min(batch, 1000)
        self._max_scanned = max_scanned
        self._max_deletions = max_deletions
        self._check_rows = check_rows

    async def collect(self, *, after: str | None = None, dry_run: bool = True) -> Collected:
        """One pass of at most `max_scanned` objects. The first pass (`after` is None) also looks at the copies, the
        uploads that were started and nobody owns, and checks that some objects that should be there are. Goes on with
        `next_after` of the answer until it is None."""
        async with self._references.exclusive() as got:
            if not got:
                return Collected(dry_run=dry_run, busy=True)
            cutoff = datetime.now(UTC) - self._grace
            result = Collected(dry_run=dry_run)
            if after is None:
                await self._copies(result, cutoff)
                await self._uploads(result, cutoff)
                await self._missing(result)
            await self._objects(result, cutoff, after)
        logger.info("Storage collection: %s", result)
        return result

    # ---- the copies whose file is gone

    async def _copies(self, result: Collected, cutoff: datetime) -> None:
        orphans = await self._references.orphan_copies(cutoff, self._max_deletions)
        result.orphan_copies = len(orphans)
        if result.dry_run or not orphans:
            return
        await self._references.delete_copies([copy.id for copy in orphans])
        await self._references.commit()  # the rows go first: what is left of them is garbage, found below
        for copy in orphans:
            if copy.multipart_id and copy.storage_key:
                await self._store.abort_multipart(copy.storage_key, copy.multipart_id)

    # ---- the uploads in parts that nobody owns

    async def _uploads(self, result: Collected, cutoff: datetime) -> None:
        owned = await self._references.owned_uploads()
        for prefix in PREFIXES:
            for upload in await self._store.list_started_uploads(prefix):
                if upload.upload_id in owned or upload.initiated >= cutoff:
                    continue
                result.started_uploads_given_up += 1
                if not result.dry_run:
                    await self._store.abort_multipart(upload.key, upload.upload_id)

    # ---- rows whose object is not there

    async def _missing(self, result: Collected) -> None:
        """Not collected: an object that should be there and is not is a loss to be told, not hidden. A few keys taken
        at random are checked each time, so that the whole is covered over the runs."""
        for key in await self._references.sample_keys(self._check_rows):
            if await self._store.head(key) is None:
                result.missing_objects += 1
                if len(result.missing_keys) < CHECKED_KEYS_SHOWN:
                    result.missing_keys.append(key)
        if result.missing_objects:
            logger.error(
                "%s objects of files of versions are missing from the storage: %s",
                result.missing_objects,
                result.missing_keys,
            )

    # ---- the objects nothing points to

    async def _objects(self, result: Collected, cutoff: datetime, after: str | None) -> None:
        for number, prefix in enumerate(PREFIXES):
            if after is not None and after > prefix and not after.startswith(prefix):
                continue  # already done by an earlier pass
            cursor = after if after is not None and after.startswith(prefix) else None
            while True:
                page = await self._store.list_objects(prefix, after=cursor, limit=self._batch)
                result.scanned += len(page.items)
                await self._sweep(result, [o for o in page.items if o.modified < cutoff])
                last = page.items[-1].key if page.items else cursor
                cursor = page.next_after
                more = cursor is not None or number < len(PREFIXES) - 1
                if more and last and self._spent(result):
                    result.next_after = last
                    return
                if cursor is None:
                    break
            after = None

    def _spent(self, result: Collected) -> bool:
        return result.scanned >= self._max_scanned or result.garbage_objects >= self._max_deletions

    async def _sweep(self, result: Collected, old: list[ListedObject]) -> None:
        """Deletes, among the objects of a page that are old enough, the ones nothing points to."""
        pointed = await self._references.referenced([o.key for o in old])
        garbage = [o for o in old if o.key not in pointed]
        if not garbage:
            return
        # Looked at again just before deleting: a row may have been committed since the first look.
        still = await self._references.referenced([o.key for o in garbage])
        garbage = [o for o in garbage if o.key not in still][: max(0, self._max_deletions - result.garbage_objects)]
        result.garbage_objects += len(garbage)
        result.garbage_bytes += sum(o.size for o in garbage)
        if garbage and not result.dry_run:
            await self._store.delete_many([o.key for o in garbage])
            result.deleted_objects += len(garbage)
