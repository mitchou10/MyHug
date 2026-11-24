import io
from collections.abc import Awaitable, Callable

import httpx2
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Dataset, DatasetMember, DatasetVersion
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services.dataset_processing import DatasetProcessor
from tests.conftest import MemoryStore
from tests.routers.test_datasets import create, share

DATASETS = "/api/datasets"
ADDRESS = f"{DATASETS}/ada/movie-reviews"
TRAIN = b"text,label\ngreat,pos\nawful,neg\nfine,pos\nbad,neg\nok,pos\n"
TEST = b"text,label\nnice,pos\nhorrible,neg\n"


@pytest.fixture
def work(db: AsyncSession, store: MemoryStore) -> Callable[[], Awaitable[None]]:
    """What the worker does: reads the files of the versions that wait. The API does not do it."""

    async def run() -> None:
        waiting = (
            (
                await db.execute(
                    select(DatasetVersion.id)
                    .where(DatasetVersion.status == "pending")
                    .order_by(DatasetVersion.created_at)
                )
            )
            .scalars()
            .all()
        )
        processor = DatasetProcessor(DatasetRepository(db), DatasetVersionRepository(db), store)
        for version_id in waiting:
            await processor.process(version_id)

    return run


def part(path: str, data: bytes, content_type: str = "text/csv") -> tuple:
    """One file of a multipart request. The path is sent as the name of the file."""
    return ("files", (path, data, content_type))


async def push(
    client: httpx2.AsyncClient,
    *files: tuple,
    remove: list[str] | None = None,
    message: str = "",
    address: str = ADDRESS,
):
    data: dict = {"message": message}
    if remove:
        data["remove"] = remove
    return await client.post(f"{address}/versions", files=list(files) or None, data=data)


async def start(client: httpx2.AsyncClient, login) -> None:
    login("u1", "ada")
    await create(client)


# ---- a first version: the API records the files, the worker reads them


async def test_sending_files_records_them_without_reading_them(client, login) -> None:
    await start(client, login)
    response = await push(
        client,
        part("data/train.csv", TRAIN),
        part("data/test.csv", TEST),
        part("README.md", b"# Reviews", "text/markdown"),
        message="first",
    )
    assert response.status_code == 201, response.text
    version = response.json()
    assert (
        version["number"],
        version["status"],
        version["error"],
        version["message"],
        version["created_by_username"],
    ) == (1, "pending", None, "first", "ada")
    assert version["size_bytes"] == len(TRAIN) + len(TEST) + len(b"# Reviews")  # known without reading anything
    assert (version["rows"], version["columns"]) == (None, [])  # not yet

    dataset = (await client.get(ADDRESS)).json()
    assert (dataset["version"], dataset["rows"], dataset["size_bytes"], dataset["processing"]) == (
        1,
        None,
        version["size_bytes"],
        "pending",
    )
    assert (dataset["splits"], dataset["columns"]) == ([], [])
    assert dataset["card"] == "# Reviews"  # the README is the card at once
    files = {f["path"]: f for f in (await client.get(f"{ADDRESS}/files")).json()}
    assert set(files) == {"data/train.csv", "data/test.csv", "README.md"}
    assert (files["data/train.csv"]["split"], files["data/train.csv"]["rows"]) == (None, None)  # not read yet
    assert files["data/train.csv"]["size_bytes"] == len(TRAIN) and len(files["data/train.csv"]["sha256"]) == 64


async def test_once_the_worker_has_read_the_files_the_dataset_describes_them(client, login, work) -> None:
    await start(client, login)
    await push(
        client,
        part("data/train.csv", TRAIN),
        part("data/test.csv", TEST),
        part("README.md", b"# Reviews", "text/markdown"),
    )
    await work()
    version = (await client.get(f"{ADDRESS}/versions")).json()[0]
    assert (version["status"], version["rows"]) == ("ready", 7)
    assert version["columns"] == [{"name": "text", "dtype": "string"}, {"name": "label", "dtype": "string"}]

    dataset = (await client.get(ADDRESS)).json()
    assert (dataset["rows"], dataset["processing"]) == (7, "ready")
    assert dataset["splits"] == [{"name": "train", "rows": 5, "files": 1}, {"name": "test", "rows": 2, "files": 1}]
    assert dataset["columns"] == version["columns"]
    assert (await client.get(DATASETS)).json()["items"][0]["rows"] == 7  # the list shows it too
    files = {f["path"]: f for f in (await client.get(f"{ADDRESS}/files")).json()}
    assert (files["data/train.csv"]["split"], files["data/train.csv"]["rows"]) == ("train", 5)
    assert (files["README.md"]["split"], files["README.md"]["rows"]) == (None, None)  # not a file of rows


async def test_a_dataset_without_files_has_nothing_to_show(client, login) -> None:
    await start(client, login)
    dataset = (await client.get(ADDRESS)).json()
    assert (dataset["version"], dataset["rows"], dataset["size_bytes"], dataset["processing"]) == (0, None, 0, None)
    assert (dataset["splits"], dataset["columns"]) == ([], [])
    assert (await client.get(f"{ADDRESS}/versions")).json() == []
    assert (await client.get(f"{ADDRESS}/files")).status_code == 404  # no version yet
    assert (await client.get(f"{ADDRESS}/rows")).status_code == 404


async def test_a_dataset_of_pictures_counts_its_pictures(client, login, work) -> None:
    await start(client, login)
    await push(
        client,
        part("a.png", b"\x89PNG1", "image/png"),
        part("b.png", b"\x89PNG2", "image/png"),
        part("README.md", b"x", "text/markdown"),
    )
    await work()
    assert (await client.get(ADDRESS)).json()["rows"] == 2  # the README is not one of them


async def test_the_paths_can_be_sent_apart_from_the_names(client, login) -> None:
    await start(client, login)
    response = await client.post(f"{ADDRESS}/versions", files=[part("blob", TRAIN)], data={"paths": ["data/train.csv"]})
    assert response.status_code == 201
    assert [f["path"] for f in (await client.get(f"{ADDRESS}/files")).json()] == ["data/train.csv"]
    assert (
        await client.post(
            f"{ADDRESS}/versions", files=[part("a", TRAIN), part("b", TRAIN)], data={"paths": ["only-one.csv"]}
        )
    ).status_code == 422


# ---- the next versions


async def test_a_new_version_keeps_the_files_it_does_not_touch(client, login, work, store: MemoryStore) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN), part("test.csv", TEST))
    await work()
    stored = len(store.objects)
    response = await push(client, part("test.csv", b"text,label\nonly,one\n"))
    assert response.status_code == 201 and response.json()["number"] == 2
    before = {f["path"]: f["rows"] for f in (await client.get(f"{ADDRESS}/files")).json()}
    assert before == {"train.csv": 5, "test.csv": None}  # what was read stays, the new file waits
    await work()
    latest = {f["path"]: f["rows"] for f in (await client.get(f"{ADDRESS}/files")).json()}
    assert latest == {"train.csv": 5, "test.csv": 1}  # replaced, and the other one stays
    old = {f["path"]: f["rows"] for f in (await client.get(f"{ADDRESS}/files", params={"version": 1})).json()}
    assert old == {"train.csv": 5, "test.csv": 2}  # the old version is as it was
    assert len(store.objects) == stored + 1  # the train file is not stored again
    assert [v["number"] for v in (await client.get(f"{ADDRESS}/versions")).json()] == [2, 1]  # the newest first
    assert (await client.get(ADDRESS)).json()["rows"] == 6


async def test_a_new_version_is_pending_whatever_the_one_before_was(client, login, work) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    await work()
    assert (await client.get(ADDRESS)).json()["processing"] == "ready"
    await push(client, part("test.csv", TEST))
    dataset = (await client.get(ADDRESS)).json()
    assert (dataset["processing"], dataset["rows"], dataset["version"]) == (
        "pending",
        None,
        2,
    )  # unknown again until read


async def test_files_are_taken_out_by_their_path(client, login) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN), part("test.csv", TEST))
    assert (await push(client, remove=["test.csv"])).status_code == 201
    assert [f["path"] for f in (await client.get(f"{ADDRESS}/files")).json()] == ["train.csv"]
    assert (await push(client, remove=["test.csv"])).status_code == 404  # it is not there any more


async def test_a_version_needs_something_to_add_or_to_remove(client, login) -> None:
    await start(client, login)
    assert (await push(client)).status_code == 422


async def test_the_same_content_twice_in_a_dataset_is_stored_once(client, login, store: MemoryStore) -> None:
    await start(client, login)
    await push(client, part("a.csv", TRAIN), part("copy-of-a.csv", TRAIN))
    assert len(store.objects) == 1


# ---- what is refused at once


@pytest.mark.parametrize("path", ["../secret.csv", "a/../../b.csv", "a//b.csv", "./a.csv", "x" * 513 + ".csv"])
async def test_a_path_that_leaves_the_dataset_is_refused(client, login, path: str) -> None:
    await start(client, login)
    assert (
        await client.post(f"{ADDRESS}/versions", files=[part("a", TRAIN)], data={"paths": [path]})
    ).status_code == 422


async def test_a_path_that_is_sent_twice_is_refused(client, login) -> None:
    await start(client, login)
    assert (await push(client, part("a.csv", TRAIN), part("a.csv", TEST))).status_code == 422


async def test_a_file_that_is_too_large_is_refused(
    client, login, monkeypatch: pytest.MonkeyPatch, store: MemoryStore
) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "DATASET_FILE_MAX_BYTES", 10)
    assert (await push(client, part("train.csv", TRAIN))).status_code == 413
    assert store.objects == {}


async def test_too_many_files_are_refused(client, login, monkeypatch: pytest.MonkeyPatch) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "DATASET_VERSION_MAX_FILES", 1)
    assert (await push(client, part("a.csv", TRAIN), part("b.csv", TEST))).status_code == 422
    assert (await push(client, part("a.csv", TRAIN))).status_code == 201
    assert (await push(client, part("b.csv", TEST))).status_code == 422  # one that is kept counts too


async def test_only_those_who_may_change_a_dataset_add_files(client, login, db: AsyncSession) -> None:
    await start(client, login)
    login("u2", "grace")
    assert (await push(client, part("train.csv", TRAIN))).status_code == 403  # may read it
    await share(db, "ada/movie-reviews", "u2", "annotator")
    assert (await push(client, part("train.csv", TRAIN))).status_code == 403
    dataset = (await db.execute(select(Dataset))).scalar_one()
    db.add(DatasetMember(dataset_id=dataset.id, user_id="u3", role="maintainer", added_by="u1"))
    await db.commit()
    login("u3", "linus")
    assert (await push(client, part("train.csv", TRAIN))).status_code == 201


async def test_nothing_is_added_without_a_login(client) -> None:
    assert (await client.post(f"{ADDRESS}/versions", files=[part("a.csv", TRAIN)])).status_code == 401


# ---- a file that cannot be read is found out by the worker


async def test_a_file_that_is_not_what_its_name_says_fails_the_version_when_it_is_read(client, login, work) -> None:
    await start(client, login)
    response = await push(
        client, part("good.csv", TRAIN), part("bad.parquet", b"not parquet", "application/octet-stream")
    )
    assert response.status_code == 201  # sending is not the moment to find out
    await work()
    version = (await client.get(f"{ADDRESS}/versions")).json()[0]
    assert version["status"] == "failed" and "bad.parquet" in version["error"]
    dataset = (await client.get(ADDRESS)).json()
    assert (dataset["processing"], dataset["rows"]) == ("failed", None)
    page = await client.get(f"{ADDRESS}/rows")
    assert page.status_code == 409  # there is nothing to preview


# ---- reading


async def test_a_file_is_downloaded_as_it_was_sent_and_counts_a_download(client, login) -> None:
    await start(client, login)
    await push(client, part("data/train.csv", TRAIN))  # no need for the worker to download
    response = await client.get(f"{ADDRESS}/files/data/train.csv")
    assert response.status_code == 200 and response.content == TRAIN
    assert response.headers["content-type"].startswith("text/csv")
    assert "train.csv" in response.headers["content-disposition"]
    await client.get(f"{ADDRESS}/files/data/train.csv")
    assert (await client.get(ADDRESS)).json()["downloads"] == 2
    assert (await client.get(f"{ADDRESS}/files/data/nothing.csv")).status_code == 404
    assert (await client.get(f"{ADDRESS}/files/data/train.csv", params={"version": 2})).status_code == 404


async def test_a_private_dataset_cannot_be_read_by_those_who_have_no_access(client, login) -> None:
    login("u1", "ada")
    await create(client, visibility="private")
    await push(client, part("train.csv", TRAIN))
    login("u2", "grace")
    for path in ("versions", "files", "files/train.csv", "rows"):
        assert (await client.get(f"{ADDRESS}/{path}")).status_code == 404, path


async def test_the_preview_waits_for_the_worker(client, login, work) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    response = await client.get(f"{ADDRESS}/rows")
    assert response.status_code == 409 and "processed" in response.json()["detail"]
    await work()
    assert (await client.get(f"{ADDRESS}/rows")).status_code == 200


async def test_the_preview_is_a_page_of_the_rows_of_a_split(client, login, work) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN), part("test.csv", TEST))
    await work()
    page = (await client.get(f"{ADDRESS}/rows", params={"limit": 2})).json()
    assert (page["split"], page["splits"], page["total"], page["limit"], page["offset"]) == (
        "train",
        ["train", "test"],
        5,
        2,
        0,
    )
    assert page["columns"] == [{"name": "text", "dtype": "string"}, {"name": "label", "dtype": "string"}]
    assert page["rows"] == [["great", "pos"], ["awful", "neg"]]
    second = (await client.get(f"{ADDRESS}/rows", params={"limit": 2, "offset": 4})).json()
    assert second["rows"] == [["ok", "pos"]]  # the last page is short
    test = (await client.get(f"{ADDRESS}/rows", params={"split": "test"})).json()
    assert (test["split"], test["total"], len(test["rows"])) == ("test", 2, 2)
    assert (await client.get(f"{ADDRESS}/rows", params={"split": "dev"})).status_code == 404


async def test_the_preview_can_be_searched(client, login, work) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    await work()
    page = (await client.get(f"{ADDRESS}/rows", params={"q": "POS", "limit": 2})).json()
    assert page["total"] == 3 and len(page["rows"]) == 2  # three match, the page has two
    assert (await client.get(f"{ADDRESS}/rows", params={"q": "zzz"})).json()["total"] == 0


async def test_the_preview_goes_through_all_the_files_of_a_split(client, login, work) -> None:
    await start(client, login)
    await push(client, part("train-0.csv", b"n\n1\n2\n3\n"), part("train-1.csv", b"n\n4\n5\n"))
    await work()
    page = (await client.get(f"{ADDRESS}/rows", params={"offset": 2, "limit": 3})).json()
    assert page["rows"] == [[3], [4], [5]] and page["total"] == 5  # a page can start in one file and end in the next


async def test_the_preview_reads_parquet_and_jsonl(client, login, work) -> None:
    await start(client, login)
    buffer = io.BytesIO()
    pq.write_table(pa.table({"id": [1, 2], "score": [0.5, None]}), buffer)
    await push(
        client,
        part("train.parquet", buffer.getvalue(), "application/octet-stream"),
        part("test.jsonl", b'{"id": 9, "score": 1}\n', "application/x-ndjson"),
    )
    await work()
    train = (await client.get(f"{ADDRESS}/rows")).json()
    assert train["rows"] == [[1, 0.5], [2, None]]
    assert train["columns"] == [{"name": "id", "dtype": "int"}, {"name": "score", "dtype": "float"}]
    assert (await client.get(f"{ADDRESS}/rows", params={"split": "test"})).json()["rows"] == [[9, 1]]


async def test_an_old_version_can_be_previewed(client, login, work) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    await work()
    await push(client, part("train.csv", b"text,label\nonly,one\n"))
    await work()
    assert (await client.get(f"{ADDRESS}/rows")).json()["total"] == 1
    assert (await client.get(f"{ADDRESS}/rows", params={"version": 1})).json()["total"] == 5


async def test_a_dataset_with_no_file_of_rows_has_nothing_to_preview(client, login, work) -> None:
    await start(client, login)
    await push(client, part("a.png", b"\x89PNG", "image/png"))
    await work()
    assert (await client.get(f"{ADDRESS}/rows")).json() == {
        "split": "",
        "splits": [],
        "columns": [],
        "rows": [],
        "total": 0,
        "limit": 10,
        "offset": 0,
    }


# ---- deleting


async def test_deleting_a_dataset_removes_its_files_from_the_storage(client, login, store: MemoryStore) -> None:
    await start(client, login)
    await push(client, part("train.csv", TRAIN))
    await push(client, part("test.csv", TEST))
    assert len(store.objects) == 2
    assert (await client.delete(ADDRESS)).status_code == 204
    assert store.objects == {}
