import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import DatasetMember, DatasetUpload, DatasetVersion
from app.repositories.dataset_uploads import DatasetUploadRepository
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository
from app.services.dataset_processing import DatasetProcessor
from app.services.dataset_uploads import part_size_for
from app.services.factory import build_dataset_uploads
from app.worker.jobs import NoJobs
from tests.conftest import MemoryStore
from tests.routers.test_datasets import create, share

ADDRESS = "/api/datasets/ada/movie-reviews"
MIB = 1024 * 1024
TRAIN = b"text,label\ngreat,pos\nawful,neg\nfine,pos\n"


async def announce(
    client: httpx2.AsyncClient, *files: tuple[str, int], remove: list[str] | None = None, message: str = ""
):
    body = {"files": [{"path": path, "size": size} for path, size in files], "remove": remove or [], "message": message}
    return await client.post(f"{ADDRESS}/uploads", json=body)


async def send_parts(
    client: httpx2.AsyncClient,
    store: MemoryStore,
    upload: dict,
    contents: dict[str, bytes],
    only: set[int] | None = None,
) -> None:
    """What the browser does: asks for the addresses of the parts, cuts each file, sends each part to its address."""
    for file in upload["files"]:
        if file.get("already_stored"):  # the dataset has it: there is nothing to send
            continue
        data = contents[file["path"]]
        numbers = [n for n in range(1, file["parts_count"] + 1) if only is None or n in only]
        response = await client.post(
            f"/api/uploads/{upload['id']}/parts", json={"file_id": file["id"], "numbers": numbers}
        )
        assert response.status_code == 200, response.text
        for part in response.json()["parts"]:
            start = (part["number"] - 1) * file["part_size"]
            store.receive(part["url"], data[start : start + file["part_size"]])


async def upload_files(client: httpx2.AsyncClient, store: MemoryStore, **contents: bytes) -> dict:
    """An upload of these files, all the parts sent, ready to be completed."""
    response = await announce(client, *((path, len(data)) for path, data in contents.items()))
    assert response.status_code == 201, response.text
    upload = response.json()
    await send_parts(client, store, upload, contents)
    return upload


async def start(client: httpx2.AsyncClient, login) -> None:
    login("u1", "ada")
    await create(client)


# ---- how a file is cut


@pytest.mark.parametrize(
    ("size", "preferred", "expected"),
    [
        (1, 64 * MIB, 64 * MIB),  # a small file is one part
        (10 * 1024 * MIB, 64 * MIB, 64 * MIB),  # 10 GiB: 160 parts of 64 MiB
        (1024 * 1024 * MIB, 64 * MIB, 105 * MIB),  # 1 TiB would need 16 384 parts of 64 MiB: the storage allows 10 000
        (100, 1 * MIB, 5 * MIB),  # never under what the storage accepts
    ],
)
def test_the_size_of_a_part_keeps_a_file_within_the_number_of_parts_the_storage_allows(
    size: int, preferred: int, expected: int
) -> None:
    assert part_size_for(size, preferred) == expected
    assert -(-size // part_size_for(size, preferred)) <= 10_000


# ---- announcing


async def test_announcing_files_says_how_to_cut_each_one(client, login, store: MemoryStore) -> None:
    await start(client, login)
    response = await announce(
        client, ("data/train.csv", len(TRAIN)), ("data/big.parquet", 12 * MIB + 7), message="first"
    )
    assert response.status_code == 201, response.text
    upload = response.json()
    assert upload["status"] == "open" and upload["version"] is None
    assert datetime.fromisoformat(upload["expires_at"]) > datetime.now(UTC) + timedelta(hours=23)
    files = {f["path"]: f for f in upload["files"]}
    assert (files["data/train.csv"]["part_size"], files["data/train.csv"]["parts_count"]) == (64 * MIB, 1)
    assert (files["data/big.parquet"]["size_bytes"], files["data/big.parquet"]["parts_count"]) == (12 * MIB + 7, 1)
    assert len(store.uploads) == 2  # the storage is ready to receive them


async def test_a_file_bigger_than_a_part_is_cut_in_several(client, login, monkeypatch: pytest.MonkeyPatch) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "UPLOAD_PART_BYTES", 5 * MIB)
    file = (await announce(client, ("big.bin", 12 * MIB + 7))).json()["files"][0]
    assert (file["part_size"], file["parts_count"]) == (5 * MIB, 3)  # 5 + 5 + 2 MiB and a bit


@pytest.mark.parametrize(
    ("files", "status"),
    [
        ([("empty.csv", 0)], 422),
        ([("../x.csv", 10)], 422),
        ([("a.csv", 10), ("a.csv", 20)], 422),
        ([("huge.bin", 10**15)], 413),
    ],
)
async def test_what_is_wrong_with_the_files_is_refused_before_anything_is_prepared(
    client, login, store: MemoryStore, files, status
) -> None:
    await start(client, login)
    assert (await announce(client, *files)).status_code == status
    assert store.uploads == {}


async def test_an_upload_needs_something_to_send_or_to_remove(client, login) -> None:
    await start(client, login)
    assert (await announce(client)).status_code == 422
    assert (await announce(client, remove=["nothing.csv"])).status_code == 404  # it is not in the dataset


async def test_too_many_files_are_refused(client, login, monkeypatch: pytest.MonkeyPatch) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "DATASET_VERSION_MAX_FILES", 1)
    assert (await announce(client, ("a.csv", 10), ("b.csv", 10))).status_code == 422


async def test_only_those_who_may_change_a_dataset_send_files(client, login, db: AsyncSession) -> None:
    await start(client, login)
    login("u2", "grace")
    assert (await announce(client, ("a.csv", 10))).status_code == 403  # may read it
    login("u1", "ada")
    await client.patch(ADDRESS, json={"visibility": "private"})
    login("u3", "linus")
    assert (await announce(client, ("a.csv", 10))).status_code == 404  # does not even see it
    await share(db, "ada/movie-reviews", "u3", "maintainer")
    assert (await announce(client, ("a.csv", 10))).status_code == 201


async def test_nothing_is_announced_without_a_login(client) -> None:
    assert (await client.post(f"{ADDRESS}/uploads", json={"files": [{"path": "a.csv", "size": 1}]})).status_code == 401


# ---- sending and completing


async def test_a_complete_upload_makes_a_version_that_waits_for_the_worker(client, login, store: MemoryStore) -> None:
    await start(client, login)
    upload = await upload_files(client, store, **{"data/train.csv": TRAIN, "README.md": b"# Reviews"})
    response = await client.post(f"/api/uploads/{upload['id']}/complete")
    assert response.status_code == 200, response.text
    version = response.json()
    assert (version["number"], version["status"], version["rows"]) == (1, "pending", None)
    assert version["size_bytes"] == len(TRAIN) + len(b"# Reviews")

    files = {f["path"]: f for f in (await client.get(f"{ADDRESS}/files")).json()}
    assert (
        files["data/train.csv"]["size_bytes"] == len(TRAIN) and files["data/train.csv"]["sha256"] is None
    )  # not read yet
    dataset = (await client.get(ADDRESS)).json()
    assert (dataset["version"], dataset["card"], dataset["processing"]) == (1, "# Reviews", "pending")
    stored = {o for o in store.objects.values()}
    assert {o.data for o in stored} == {TRAIN, b"# Reviews"} and store.uploads == {}  # nothing is left half-way
    assert (await client.get(f"/api/uploads/{upload['id']}")).json()["status"] == "completed"


async def test_a_file_in_several_parts_is_put_back_together(
    client, login, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "UPLOAD_PART_BYTES", 5 * MIB)
    data = bytes(range(256)) * (12 * MIB // 256) + b"end"
    upload = await upload_files(client, store, **{"big.bin": data})
    assert upload["files"][0]["parts_count"] == 3
    assert (await client.post(f"/api/uploads/{upload['id']}/complete")).status_code == 200
    assert next(iter(store.objects.values())).data == data


async def test_the_worker_can_read_a_file_that_came_in_parts(
    client, login, store: MemoryStore, db: AsyncSession
) -> None:
    await start(client, login)
    upload = await upload_files(client, store, **{"train.csv": TRAIN})
    await client.post(f"/api/uploads/{upload['id']}/complete")
    version_id = (await db.execute(select(DatasetVersion.id))).scalar_one()
    done = await DatasetProcessor(
        DatasetRepository(db), DatasetVersionRepository(db), DatasetUploadRepository(db), store
    ).process(version_id)
    assert done is not None and (done.status, done.rows) == ("ready", 3)
    assert (await client.get(f"{ADDRESS}/rows")).json()["rows"][0] == ["great", "pos"]
    assert (await client.get(f"{ADDRESS}/files/train.csv")).status_code == 302  # and it downloads


async def test_completing_twice_gives_the_same_version(client, login, store: MemoryStore) -> None:
    await start(client, login)
    upload = await upload_files(client, store, **{"train.csv": TRAIN})
    first = (await client.post(f"/api/uploads/{upload['id']}/complete")).json()
    second = await client.post(f"/api/uploads/{upload['id']}/complete")  # the answer was lost: the browser asks again
    assert second.status_code == 200 and second.json()["number"] == first["number"] == 1
    assert len((await client.get(f"{ADDRESS}/versions")).json()) == 1


async def test_a_new_version_keeps_the_files_of_the_previous_one_and_takes_out_what_is_asked(
    client, login, store: MemoryStore
) -> None:
    await start(client, login)
    first = await upload_files(client, store, **{"a.csv": TRAIN, "b.csv": TRAIN + b"x\n"})
    await client.post(f"/api/uploads/{first['id']}/complete")
    body = {"files": [{"path": "c.csv", "size": len(TRAIN)}], "remove": ["b.csv"], "message": "swap"}
    second = (await client.post(f"{ADDRESS}/uploads", json=body)).json()
    await send_parts(client, store, second, {"c.csv": TRAIN})
    version = (await client.post(f"/api/uploads/{second['id']}/complete")).json()
    assert (version["number"], version["message"]) == (2, "swap")
    assert sorted(f["path"] for f in (await client.get(f"{ADDRESS}/files")).json()) == ["a.csv", "c.csv"]


# ---- resuming


async def test_what_arrived_is_known_so_an_upload_can_be_resumed(
    client, login, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "UPLOAD_PART_BYTES", 5 * MIB)
    data = b"z" * (12 * MIB)
    upload = (await announce(client, ("big.bin", len(data)))).json()
    await send_parts(
        client, store, upload, {"big.bin": data}, only={1, 3}
    )  # the connection broke after two of the three

    state = (await client.get(f"/api/uploads/{upload['id']}", params={"parts": True})).json()
    received = state["files"][0]["received"]
    assert [(p["number"], p["size"]) for p in received] == [(1, 5 * MIB), (3, 2 * MIB)]
    assert (await client.get(f"/api/uploads/{upload['id']}")).json()["files"][0]["received"] is None  # only when asked

    assert (await client.post(f"/api/uploads/{upload['id']}/complete")).status_code == 422  # not yet
    await send_parts(client, store, upload, {"big.bin": data}, only={2})  # the missing one, and nothing else
    assert (await client.post(f"/api/uploads/{upload['id']}/complete")).status_code == 200


async def test_a_part_that_is_missing_or_has_the_wrong_size_is_named(
    client, login, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "UPLOAD_PART_BYTES", 5 * MIB)
    upload = (await announce(client, ("big.bin", 12 * MIB))).json()
    file = upload["files"][0]
    urls = {
        p["number"]: p["url"]
        for p in (
            await client.post(f"/api/uploads/{upload['id']}/parts", json={"file_id": file["id"], "numbers": [1, 2, 3]})
        ).json()["parts"]
    }
    store.receive(urls[1], b"a" * (5 * MIB))
    store.receive(urls[3], b"c" * (2 * MIB))
    missing = await client.post(f"/api/uploads/{upload['id']}/complete")
    assert (
        missing.status_code == 422
        and "part 2 is missing" in missing.json()["detail"]
        and "big.bin" in missing.json()["detail"]
    )
    store.receive(urls[2], b"b" * 10)  # arrived, but not the size announced
    wrong = await client.post(f"/api/uploads/{upload['id']}/complete")
    assert wrong.status_code == 422 and "part 2" in wrong.json()["detail"]
    assert store.objects == {}  # nothing was put together, and the upload can still be fixed
    assert (await client.get(f"/api/uploads/{upload['id']}")).json()["status"] == "open"


async def test_the_signed_addresses_are_asked_for_the_parts_the_file_has(client, login, store: MemoryStore) -> None:
    await start(client, login)
    upload = (await announce(client, ("a.csv", 10), ("b.csv", 10))).json()
    first, second = upload["files"]
    answer = (
        await client.post(f"/api/uploads/{upload['id']}/parts", json={"file_id": first["id"], "numbers": [1]})
    ).json()
    assert answer["expires_in"] == settings.SIGNED_ADDRESS_SECONDS and answer["parts"][0]["number"] == 1
    for numbers in ([0], [2], [1, 99]):  # the file has one part
        assert (
            await client.post(f"/api/uploads/{upload['id']}/parts", json={"file_id": first["id"], "numbers": numbers})
        ).status_code == 422
    assert (
        await client.post(f"/api/uploads/{upload['id']}/parts", json={"file_id": str(uuid.uuid4()), "numbers": [1]})
    ).status_code == 404
    assert (
        await client.post(f"/api/uploads/{upload['id']}/parts", json={"file_id": second["id"], "numbers": []})
    ).status_code == 422


# ---- whose upload it is, and when it is over


async def test_an_upload_is_visible_only_to_the_one_who_started_it_and_the_admins(client, login) -> None:
    await start(client, login)
    upload = (await announce(client, ("a.csv", 10))).json()
    login("u2", "grace")
    assert (await client.get(f"/api/uploads/{upload['id']}")).status_code == 404
    assert (await client.post(f"/api/uploads/{upload['id']}/complete")).status_code == 404
    assert (await client.delete(f"/api/uploads/{upload['id']}")).status_code == 404
    login("a1", "root", admin=True)
    assert (await client.get(f"/api/uploads/{upload['id']}")).status_code == 200
    assert (await client.get(f"/api/uploads/{uuid.uuid4()}")).status_code == 404


async def test_a_person_who_lost_the_right_to_change_the_dataset_cannot_go_on(client, login, db: AsyncSession) -> None:
    await start(client, login)
    await share(db, "ada/movie-reviews", "u2", "maintainer")
    login("u2", "grace")
    upload = (await announce(client, ("a.csv", 10))).json()
    await db.execute(delete(DatasetMember))
    await db.commit()
    assert (
        await client.post(
            f"/api/uploads/{upload['id']}/parts", json={"file_id": upload["files"][0]["id"], "numbers": [1]}
        )
    ).status_code == 403


async def test_giving_up_frees_what_was_prepared_and_closes_the_upload(client, login, store: MemoryStore) -> None:
    await start(client, login)
    upload = await upload_files(client, store, **{"a.csv": TRAIN})
    assert (await client.delete(f"/api/uploads/{upload['id']}")).status_code == 204
    assert store.uploads == {} and store.objects == {}
    assert (await client.get(f"/api/uploads/{upload['id']}")).json()["status"] == "aborted"
    assert (await client.post(f"/api/uploads/{upload['id']}/complete")).status_code == 409
    assert (await client.delete(f"/api/uploads/{upload['id']}")).status_code == 409
    assert (await client.get(f"{ADDRESS}/versions")).json() == []


async def test_an_upload_that_took_too_long_is_closed(client, login, store: MemoryStore, db: AsyncSession) -> None:
    await start(client, login)
    upload = await upload_files(client, store, **{"a.csv": TRAIN})
    await db.execute(update(DatasetUpload).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    await db.commit()
    assert (await client.post(f"/api/uploads/{upload['id']}/complete")).status_code == 409
    assert (await client.get(f"/api/uploads/{upload['id']}")).json()["status"] == "expired"
    assert store.uploads == {}  # the parts that had arrived are freed


async def test_the_uploads_that_were_abandoned_are_given_up_by_a_job(
    client, login, store: MemoryStore, db: AsyncSession
) -> None:
    await start(client, login)
    await announce(client, ("a.csv", 10))
    fresh = (await announce(client, ("b.csv", 10))).json()
    await db.execute(
        update(DatasetUpload)
        .where(DatasetUpload.id != uuid.UUID(fresh["id"]))
        .values(expires_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db.commit()
    service = build_dataset_uploads(db, store, NoJobs())
    assert await service.expire_stale() == 1  # only the one whose time is over
    assert len(store.uploads) == 1
    assert await service.expire_stale() == 0
    assert (await db.execute(select(DatasetUpload.status).order_by(DatasetUpload.status))).scalars().all() == [
        "expired",
        "open",
    ]


# ---- when the storage breaks while putting the parts together


async def test_when_the_storage_breaks_while_joining_nothing_is_left_behind(
    client, login, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start(client, login)
    upload = await upload_files(client, store, **{"a.csv": TRAIN, "b.csv": TRAIN + b"x\n"})
    real = store.complete_multipart
    calls = 0

    async def break_on_second(key: str, upload_id: str, parts) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConnectionError("storage down")
        await real(key, upload_id, parts)

    monkeypatch.setattr(store, "complete_multipart", break_on_second)
    with pytest.raises(ConnectionError):
        await client.post(f"/api/uploads/{upload['id']}/complete")
    assert store.objects == {}  # the file that was joined is taken back
    assert store.uploads == {}  # and the other one is given up
    assert (await client.get(f"/api/uploads/{upload['id']}")).json()["status"] == "aborted"
    assert (await client.get(f"{ADDRESS}/versions")).json() == []


async def test_the_size_of_the_joined_file_is_checked(
    client, login, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start(client, login)
    upload = await upload_files(client, store, **{"a.csv": TRAIN})
    real = store.complete_multipart

    async def truncate(key: str, upload_id: str, parts) -> None:
        await real(key, upload_id, parts)
        store.objects[key] = store.objects[key].model_copy(update={"data": b"short"})

    monkeypatch.setattr(store, "complete_multipart", truncate)
    response = await client.post(f"/api/uploads/{upload['id']}/complete")
    assert response.status_code == 422 and "5 bytes" in response.json()["detail"]
    assert store.objects == {}


async def test_the_uploads_of_a_deleted_dataset_go_with_it(client, login, store: MemoryStore, db: AsyncSession) -> None:
    await start(client, login)
    await announce(client, ("a.csv", 10))
    assert (await client.delete(ADDRESS)).status_code == 204
    assert store.uploads == {}  # what was being sent is given up in the storage
    assert (await db.execute(select(DatasetUpload))).first() is None
    assert await DatasetUploadRepository(db).open_until(datetime.now(UTC) + timedelta(days=9)) == []


# ---- a file the dataset already holds is not sent again


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def known_file(client: httpx2.AsyncClient, path: str = "train.csv", data: bytes = TRAIN) -> None:
    """A file sent through the API, which fingerprints what it receives: the dataset knows it for sure."""
    response = await client.post(f"{ADDRESS}/versions", files=[("files", (path, data, "text/csv"))])
    assert response.status_code == 201, response.text


async def announce_with_sha(client: httpx2.AsyncClient, path: str, data: bytes, fingerprint: str | None = None):
    file = {"path": path, "size": len(data), "sha256": sha(data) if fingerprint is None else fingerprint}
    return await client.post(f"{ADDRESS}/uploads", json={"files": [file]})


async def test_a_file_the_dataset_already_holds_is_not_sent_again(client, login, store: MemoryStore) -> None:
    await start(client, login)
    await known_file(client)
    before = dict(store.objects)
    response = await announce_with_sha(client, "copy.csv", TRAIN)
    assert response.status_code == 201, response.text
    upload = response.json()
    file = upload["files"][0]
    assert (file["already_stored"], file["parts_count"], file["part_size"]) == (True, 0, 0)
    assert store.uploads == {}  # nothing was prepared in the storage

    version = (await client.post(f"/api/uploads/{upload['id']}/complete")).json()
    assert (version["number"], version["status"]) == (2, "pending")
    files = {f["path"]: f for f in (await client.get(f"{ADDRESS}/files")).json()}
    assert set(files) == {"train.csv", "copy.csv"}
    assert files["copy.csv"]["sha256"] == files["train.csv"]["sha256"] == sha(TRAIN)  # known, not announced
    assert store.objects == before  # one object, two paths
    location = (await client.get(f"{ADDRESS}/files/copy.csv")).headers["location"]
    assert store.objects[location.removeprefix("memory://get/")].data == TRAIN


async def test_a_file_already_held_and_a_new_one_go_in_the_same_upload(client, login, store: MemoryStore) -> None:
    await start(client, login)
    await known_file(client)
    body = {"files": [{"path": "copy.csv", "size": len(TRAIN), "sha256": sha(TRAIN)}, {"path": "new.csv", "size": 4}]}
    upload = (await client.post(f"{ADDRESS}/uploads", json=body)).json()
    assert {f["path"]: f["already_stored"] for f in upload["files"]} == {"copy.csv": True, "new.csv": False}
    assert len(store.uploads) == 1  # only the new one is prepared
    await send_parts(client, store, upload, {"new.csv": b"n\n1\n"})
    assert (await client.post(f"/api/uploads/{upload['id']}/complete")).status_code == 200
    assert sorted(f["path"] for f in (await client.get(f"{ADDRESS}/files")).json()) == [
        "copy.csv",
        "new.csv",
        "train.csv",
    ]


async def test_the_uppercase_fingerprint_is_accepted_and_a_bad_one_is_refused(client, login) -> None:
    await start(client, login)
    await known_file(client)
    assert (await announce_with_sha(client, "a.csv", TRAIN, sha(TRAIN).upper())).json()["files"][0][
        "already_stored"
    ] is True
    for bad in ("abc", "g" * 64, sha(TRAIN) + "0"):
        assert (await announce_with_sha(client, "b.csv", TRAIN, bad)).status_code == 422


async def test_a_file_the_dataset_does_not_know_is_sent_as_usual(client, login, store: MemoryStore) -> None:
    await start(client, login)
    await known_file(client)
    other = b"text,label\nother,pos\n"
    file = (await announce_with_sha(client, "other.csv", other)).json()["files"][0]
    assert (file["already_stored"], file["parts_count"]) == (False, 1)
    assert len(store.uploads) == 1


async def test_the_same_fingerprint_with_another_size_is_not_the_same_file(client, login) -> None:
    await start(client, login)
    await known_file(client)
    response = await client.post(
        f"{ADDRESS}/uploads", json={"files": [{"path": "x.csv", "size": len(TRAIN) + 1, "sha256": sha(TRAIN)}]}
    )
    assert response.json()["files"][0]["already_stored"] is False


async def test_a_fingerprint_that_somebody_announced_is_not_believed(client, login, store: MemoryStore) -> None:
    """A file sent in parts has no fingerprint until a worker reads it: a wrong claim must not stand for it."""
    await start(client, login)
    upload = await upload_files(client, store, **{"parts.csv": TRAIN})
    await client.post(f"/api/uploads/{upload['id']}/complete")
    again = (await announce_with_sha(client, "again.csv", TRAIN)).json()["files"][0]
    assert again["already_stored"] is False  # it has to be sent, even if the content is the same


async def test_a_file_is_only_looked_for_in_the_dataset_it_is_sent_to(client, login, store: MemoryStore) -> None:
    await start(client, login)
    await create(client, "other")
    other = "/api/datasets/ada/other"
    assert (
        await client.post(f"{other}/versions", files=[("files", ("train.csv", TRAIN, "text/csv"))])
    ).status_code == 201
    assert (await announce_with_sha(client, "train.csv", TRAIN)).json()["files"][0]["already_stored"] is False


async def test_nothing_can_be_sent_for_a_file_that_is_already_stored(client, login) -> None:
    await start(client, login)
    await known_file(client)
    upload = (await announce_with_sha(client, "copy.csv", TRAIN)).json()
    file_id = upload["files"][0]["id"]
    assert (
        await client.post(f"/api/uploads/{upload['id']}/parts", json={"file_id": file_id, "numbers": [1]})
    ).status_code == 422
    state = (await client.get(f"/api/uploads/{upload['id']}", params={"parts": True})).json()
    assert state["files"][0]["received"] == []


async def test_a_file_that_left_the_storage_before_the_end_is_said_to_be_sent_again(
    client, login, store: MemoryStore
) -> None:
    await start(client, login)
    await known_file(client)
    upload = (await announce_with_sha(client, "copy.csv", TRAIN)).json()
    store.objects.clear()  # what it pointed to is gone
    response = await client.post(f"/api/uploads/{upload['id']}/complete")
    assert response.status_code == 422 and "copy.csv" in response.json()["detail"]
    assert (await client.get(f"{ADDRESS}/versions")).json()[0]["number"] == 1  # no new version


async def test_giving_up_or_failing_never_takes_back_an_object_that_other_files_use(
    client, login, store: MemoryStore
) -> None:
    await start(client, login)
    await known_file(client)
    kept = dict(store.objects)
    upload = (await announce_with_sha(client, "copy.csv", TRAIN)).json()
    assert (await client.delete(f"/api/uploads/{upload['id']}")).status_code == 204
    assert store.objects == kept
    second = (await announce_with_sha(client, "copy.csv", TRAIN)).json()
    assert (await client.delete(ADDRESS)).status_code == 204  # the dataset goes with an upload open
    assert store.objects == {} and store.uploads == {} and second["status"] == "open"
