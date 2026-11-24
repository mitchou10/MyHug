import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs import NoJobs
from app.models import DatasetFile, DatasetFileDerivative
from app.repositories.dataset_derivatives import DatasetDerivativeRepository
from app.services import tables
from app.services.errors import DerivativeNotFound, NotBeingProcessed
from app.services.factory import build_dataset_derivatives, build_dataset_versions
from tests.conftest import MemoryStore
from tests.reading import Reader
from tests.services.test_dataset_processing import setup

CSV = b"text,score\n" + b"".join(f"row {i},{i}\n".encode() for i in range(30))


@pytest.fixture(autouse=True)
def small_files_are_copied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every csv is big enough for a copy in these tests."""
    monkeypatch.setattr(settings, "DERIVATIVE_MIN_BYTES", 0)


async def copies(db: AsyncSession) -> list[DatasetFileDerivative]:
    return list((await db.execute(select(DatasetFileDerivative).order_by(DatasetFileDerivative.created_at))).scalars())


async def ready_version(db: AsyncSession, store: MemoryStore, *files: tuple[str, bytes]):
    version = await setup(db, store, *files)
    await Reader(db, store).process(version.id)
    return version


def parquet_of(data: bytes, group: int = 10) -> bytes:
    """What the worker would make from the csv: the same rows, in groups."""
    rows = list(tables.iter_rows("a.csv", data))
    table = pa.table({"text": [r[0] for r in rows], "score": [r[1] for r in rows]})
    sink = io.BytesIO()
    pq.write_table(table, sink, row_group_size=group)
    return sink.getvalue()


async def worker_makes(db: AsyncSession, store: MemoryStore, derivative: DatasetFileDerivative, data: bytes = CSV):
    """Plays the worker for a copy: claims it, sends the parts to their signed address, says what it holds."""
    service = build_dataset_derivatives(db, store)
    claimed = await service.claim(derivative.id)
    assert claimed is not None
    sent = parquet_of(data)
    urls = await service.part_urls(derivative.id, [1, 2])
    store.receive(urls[1], sent[: len(sent) // 2])
    store.receive(urls[2], sent[len(sent) // 2 :])
    rows = len(list(tables.iter_rows("a.csv", data)))
    return await service.complete(derivative.id, rows, [tables.Column("text", "string"), tables.Column("score", "int")])


# ---- which files get a copy


async def test_a_big_tabular_file_gets_a_copy_when_its_version_is_ready(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV), ("README.md", b"# x"))
    (copy,) = await copies(db)
    assert (copy.status, copy.source_path, copy.kind, copy.source_size_bytes) == (
        "pending",
        "train.csv",
        "parquet",
        len(CSV),
    )


async def test_small_files_parquet_files_and_other_files_get_none(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "DERIVATIVE_MIN_BYTES", 1000)
    store = MemoryStore()
    await ready_version(db, store, ("small.csv", b"n\n1\n"), ("README.md", b"# x" * 1000))
    assert await copies(db) == []


async def test_a_file_that_is_already_parquet_is_not_converted(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.parquet", parquet_of(CSV)))
    assert await copies(db) == []


async def test_a_source_over_the_maximum_is_left_alone(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DERIVATIVE_MAX_SOURCE_BYTES", 10)
    await ready_version(db, MemoryStore(), ("train.csv", CSV))
    assert await copies(db) == []


async def test_a_file_kept_in_the_next_version_keeps_its_copy_and_is_not_copied_again(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (first,) = await copies(db)
    second = await setup(db, store, ("test.csv", CSV.replace(b"row", b"new")))  # train.csv is carried over
    await Reader(db, store).process(second.id)
    found = await copies(db)
    assert len(found) == 2 and first.id in {c.id for c in found}  # one for the new file, none more for the old


async def test_two_files_with_the_same_content_share_one_copy(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("a.csv", CSV), ("b.csv", CSV))
    assert len(await copies(db)) == 1


async def test_reading_a_ready_version_again_does_not_make_the_copies_again(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await ready_version(db, store, ("train.csv", CSV))
    await Reader(db, store).process(version.id)
    assert len(await copies(db)) == 1


async def test_a_job_is_queued_for_each_new_copy(db: AsyncSession) -> None:
    queued: list[uuid.UUID] = []

    class Recorder(NoJobs):
        async def convert_file(self, derivative_id: uuid.UUID) -> None:
            queued.append(derivative_id)

    from app.services.factory import build_dataset_processing

    store = MemoryStore()
    version = await setup(db, store, ("train.csv", CSV))
    service = build_dataset_processing(db, store, Recorder())
    claimed = await service.claim(version.id)
    assert claimed is not None
    files = await Reader(db, store).service._versions.files(version.id)  # noqa: SLF001
    found = {f.id: f for f in files}
    from app.services.dataset_processing import FileRead

    await service.complete(
        version.id,
        [
            FileRead(
                id=f.id,
                size_bytes=f.size_bytes,
                sha256=None,
                rows=30,
                columns=[tables.Column("text", "string"), tables.Column("score", "int")],
            )
            for f in found.values()
        ],
    )
    assert queued == [(await copies(db))[0].id]


# ---- making a copy


async def test_the_worker_claims_a_copy_and_gets_the_source_and_the_size_of_parts(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    claimed = await build_dataset_derivatives(db, store).claim(copy.id)
    assert claimed is not None and claimed.source_path == "train.csv"
    assert claimed.source_url.startswith("memory://get/") and claimed.part_bytes == settings.DERIVATIVE_PART_BYTES
    await db.refresh(copy)
    assert copy.status == "processing" and copy.attempts == 1 and copy.multipart_id
    assert (await build_dataset_derivatives(db, store).claim(copy.id)) is None  # one worker at a time


async def test_a_finished_copy_is_ready_and_known(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    done = await worker_makes(db, store, copy)
    assert (done.status, done.rows, done.columns[1]) == ("ready", 30, {"name": "score", "dtype": "int"})
    assert done.storage_key in store.objects and done.size_bytes == len(store.objects[done.storage_key].data)
    assert done.multipart_id is None and not store.uploads
    assert set(await build_dataset_derivatives(db, store).ready_for([copy.source_storage_key])) == {
        copy.source_storage_key
    }


async def test_a_copy_with_a_different_number_of_rows_fails_the_copy_and_not_the_version(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    service = build_dataset_derivatives(db, store)
    await service.claim(copy.id)
    store.receive((await service.part_urls(copy.id, [1]))[1], parquet_of(CSV))
    done = await service.complete(copy.id, 29, [])
    assert done.status == "failed" and "29" in (done.error or "") and "30" in (done.error or "")
    assert not [k for k in store.objects if k.startswith("derived/")]  # the wrong copy is not kept
    await db.refresh(version)
    assert version.status == "ready"


async def test_a_copy_that_sent_no_part_is_failed(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    service = build_dataset_derivatives(db, store)
    await service.claim(copy.id)
    assert (await service.complete(copy.id, 30, [])).status == "failed"


async def test_a_failed_copy_frees_what_was_sent_and_can_be_made_again(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    service = build_dataset_derivatives(db, store)
    await service.claim(copy.id)
    assert (await service.fail(copy.id, "train.csv is not a csv")).status == "failed"
    assert not store.uploads  # the parts that were started are given up
    again = await service.claim(copy.id)
    assert again is not None
    await db.refresh(copy)
    assert copy.attempts == 2 and copy.error is None


async def test_a_released_copy_waits_again(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    service = build_dataset_derivatives(db, store)
    await service.claim(copy.id)
    await service.release(copy.id)
    await db.refresh(copy)
    assert copy.status == "pending"


async def test_a_copy_whose_worker_died_is_taken_again_and_its_parts_are_given_up(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    service = build_dataset_derivatives(db, store)
    await service.claim(copy.id)
    first = next(iter(store.uploads))
    await db.execute(update(DatasetFileDerivative).values(processing_started_at=datetime.now(UTC) - timedelta(hours=1)))
    await db.commit()
    assert await service.claim(copy.id) is not None
    assert first not in store.uploads and len(store.uploads) == 1  # the dead worker's upload was given up


async def test_a_copy_that_keeps_being_interrupted_is_given_up(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    await db.execute(update(DatasetFileDerivative).values(attempts=3))
    await db.commit()
    (copy,) = await copies(db)
    assert await build_dataset_derivatives(db, store).claim(copy.id) is None
    await db.refresh(copy)
    assert copy.status == "failed" and "interrupted" in (copy.error or "")


async def test_the_worker_cannot_report_on_a_copy_it_does_not_hold(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    service = build_dataset_derivatives(db, store)
    with pytest.raises(NotBeingProcessed):
        await service.complete(copy.id, 30, [])
    with pytest.raises(NotBeingProcessed):
        await service.part_urls(copy.id, [1])
    with pytest.raises(DerivativeNotFound):
        await service.fail(uuid.uuid4(), "x")


async def test_the_sweep_finds_the_copies_nobody_is_making(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("old.csv", CSV))
    await ready_version(db, store, ("new.csv", CSV.replace(b"row", b"new")))
    old, new = await copies(db)
    await db.execute(
        update(DatasetFileDerivative)
        .where(DatasetFileDerivative.id == old.id)
        .values(created_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db.commit()
    assert await build_dataset_derivatives(db, store).waiting() == [old.id] and new.id != old.id


# ---- reading with the copy


def versions_service(db: AsyncSession, store: MemoryStore):
    return build_dataset_versions(db, store, NoJobs())


async def rows(db: AsyncSession, store: MemoryStore, **options):
    from app.services.dataset_versions import RowsPage  # noqa: F401
    from tests.services.test_dataset_services import ADA

    return await versions_service(db, store).rows(
        ADA, "ada", "reviews", split=None, number=None, offset=0, limit=10, query=None, **options
    )


async def made(db: AsyncSession, store: MemoryStore) -> DatasetFileDerivative:
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    return await worker_makes(db, store, copy)


def never_read(store: MemoryStore, key: str) -> None:
    """The original is taken away: what is shown can only come from the copy."""
    del store.objects[key]


async def test_the_preview_reads_the_copy_and_shows_what_the_file_shows(db: AsyncSession) -> None:
    store = MemoryStore()
    before = None
    await ready_version(db, store, ("train.csv", CSV))
    before = await rows(db, store)  # no copy yet: read from the csv
    (copy,) = await copies(db)
    await worker_makes(db, store, copy)
    never_read(store, copy.source_storage_key)
    after = await rows(db, store)
    assert after.rows == before.rows and after.total == before.total == 30 and after.columns == before.columns


async def test_a_page_in_the_middle_of_the_copy_reads_the_right_rows(db: AsyncSession) -> None:
    from tests.services.test_dataset_services import ADA

    store = MemoryStore()
    copy = await made(db, store)
    never_read(store, copy.source_storage_key)
    page = await versions_service(db, store).rows(
        ADA, "ada", "reviews", split=None, number=None, offset=8, limit=5, query=None
    )
    assert [r[1] for r in page.rows] == [8, 9, 10, 11, 12]  # across the first two groups of ten


async def test_a_page_past_the_end_is_empty(db: AsyncSession) -> None:
    from tests.services.test_dataset_services import ADA

    store = MemoryStore()
    copy = await made(db, store)
    never_read(store, copy.source_storage_key)
    page = await versions_service(db, store).rows(
        ADA, "ada", "reviews", split=None, number=None, offset=28, limit=10, query=None
    )
    assert [r[1] for r in page.rows] == [28, 29] and page.total == 30


async def test_a_search_goes_through_the_copy_too(db: AsyncSession) -> None:
    from tests.services.test_dataset_services import ADA

    store = MemoryStore()
    copy = await made(db, store)
    never_read(store, copy.source_storage_key)
    page = await versions_service(db, store).rows(
        ADA, "ada", "reviews", split=None, number=None, offset=0, limit=10, query="row 2"
    )
    assert [r[1] for r in page.rows] == [2, 20, 21, 22, 23, 24, 25, 26, 27, 28] and page.total == 11


async def test_when_the_copy_cannot_be_read_the_preview_goes_on_with_the_file(db: AsyncSession) -> None:
    store = MemoryStore()
    copy = await made(db, store)
    assert copy.storage_key is not None
    store.objects[copy.storage_key] = MemoryStore.stored(b"not a parquet file at all", "application/octet-stream")
    page = await rows(db, store)
    assert page.total == 30 and page.rows[0] == ["row 0", 0]


async def test_a_copy_that_is_not_ready_is_not_read(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    service = build_dataset_derivatives(db, store)
    assert await service.ready_for([(await copies(db))[0].source_storage_key]) == {}


async def test_the_columns_of_a_nested_copy_are_read_back_as_they_were(db: AsyncSession) -> None:
    from app.services import parquet_pages

    sink = io.BytesIO()
    schema = pa.schema([pa.field("tags", pa.string(), metadata={b"json": b"1"}), pa.field("n", pa.int64())])
    pq.write_table(
        pa.Table.from_pylist([{"tags": json.dumps(["a"]), "n": 1}, {"tags": None, "n": 2}], schema=schema), sink
    )
    store = MemoryStore()
    store.objects["k"] = MemoryStore.stored(sink.getvalue(), "application/octet-stream")
    assert await parquet_pages.page(store, "k", len(sink.getvalue()), 0, 10) == [[["a"], 1], [None, 2]]


async def test_a_copy_does_not_count_in_the_rows_or_the_size_of_the_dataset(db: AsyncSession) -> None:
    store = MemoryStore()
    version = await ready_version(db, store, ("train.csv", CSV))
    size, rows_ = version.size_bytes, version.rows
    (copy,) = await copies(db)
    await worker_makes(db, store, copy)
    await db.refresh(version)
    assert (version.size_bytes, version.rows) == (size, rows_) == (len(CSV), 30)
    files = (await db.execute(select(DatasetFile.path))).scalars().all()
    assert not [f for f in files if f.endswith(".parquet")]  # not a file of the dataset


async def test_the_unique_key_stops_two_copies_of_the_same_source(db: AsyncSession) -> None:
    store = MemoryStore()
    await ready_version(db, store, ("train.csv", CSV))
    (copy,) = await copies(db)
    again = await DatasetDerivativeRepository(db).create_missing(
        [(copy.source_storage_key, "other.csv", len(CSV))], copy.params_hash
    )
    assert again == []
