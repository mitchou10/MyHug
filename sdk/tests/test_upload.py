import asyncio
from pathlib import Path

import httpx2
import pytest

from myhug import errors
from myhug._transfer import LocalFile, Progress
from myhug._upload import Routes, aabort, abort, aupload, upload
from tests.fake import FakePlatform, sha

DATASET = Routes("/api/datasets/ada/sentiment/uploads", "/api/uploads")
MODEL = Routes("/api/models/ada/sentiment/uploads", "/api/model-uploads")


def local(tmp_path: Path, name: str, data: bytes) -> LocalFile:
    source = tmp_path / "src" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    return LocalFile(source, name)


async def send(driver, routes: Routes, files: list[LocalFile], **options):
    return await driver.call(upload if driver.mode == "sync" else aupload, routes, files, **options)


async def test_the_parts_go_to_the_storage_and_the_version_is_completed(
    driver, platform: FakePlatform, tmp_path
) -> None:
    data = bytes(range(10))  # 10 bytes in parts of 4: 4 + 4 + 2
    seen: list[Progress] = []
    version = await send(driver, DATASET, [local(tmp_path, "data/a.bin", data)], message="first", progress=seen.append)
    assert version == {"number": 1, "status": "pending"}
    assert platform.assembled == {"data/a.bin": data}
    assert platform.announced[0]["message"] == "first" and platform.announced[0]["files"][0]["size"] == 10
    assert seen[0] == Progress(0, 10) and seen[-1] == Progress(10, 10)
    assert [p.done for p in seen] == sorted(p.done for p in seen)  # only goes forward


async def test_nothing_of_the_token_goes_to_the_storage(driver, platform: FakePlatform, tmp_path) -> None:
    await send(driver, DATASET, [local(tmp_path, "a.bin", b"12345678")])
    puts = [r for r in platform.requests if r.url.host == "storage.test"]
    assert puts and all("authorization" not in r.headers for r in puts)


async def test_a_model_goes_to_its_own_routes_with_what_is_added_to_the_announcement(
    driver, platform, tmp_path
) -> None:
    code = {"url": "https://github.com/o/r", "ref": "main"}
    await send(driver, MODEL, [local(tmp_path, "w.bin", b"abcd")], extra={"code": code})
    assert platform.announced[0]["code"] == code
    assert platform.api_calls("POST", f"/api/model-uploads/{next(iter(platform.uploads))}/complete")


async def test_paths_to_remove_are_announced_with_the_files(driver, platform, tmp_path) -> None:
    await send(driver, DATASET, [local(tmp_path, "new.bin", b"abcd")], remove=["old.bin", "older.bin"])
    assert platform.announced[0]["remove"] == ["old.bin", "older.bin"]


async def test_a_file_the_platform_already_holds_is_not_sent_again(driver, platform, tmp_path) -> None:
    same, other = local(tmp_path, "same.bin", b"abcdefgh"), local(tmp_path, "other.bin", b"12345678")
    platform.held.add(sha(b"abcdefgh"))
    seen: list[Progress] = []
    await send(driver, DATASET, [same, other], progress=seen.append)
    assert platform.announced[0]["files"][0]["sha256"] == sha(b"abcdefgh")
    assert platform.assembled == {"other.bin": b"12345678"}  # only the other was sent
    assert seen[-1].total == 8  # and the progress counts only what was to send


async def test_nothing_is_sent_when_everything_is_already_there(driver, platform, tmp_path) -> None:
    platform.held.add(sha(b"abcdefgh"))
    await send(driver, DATASET, [local(tmp_path, "same.bin", b"abcdefgh")])
    assert not [r for r in platform.requests if r.url.host == "storage.test"]
    assert platform.completed


async def test_without_fingerprints_the_files_are_announced_without_them(driver, platform, tmp_path) -> None:
    platform.held.add(sha(b"abcdefgh"))
    await send(driver, DATASET, [local(tmp_path, "same.bin", b"abcdefgh")], fingerprint=False)
    assert platform.announced[0]["files"][0]["sha256"] is None
    assert platform.assembled == {"same.bin": b"abcdefgh"}  # so it was sent


async def test_a_part_that_is_refused_is_tried_again_with_another_address(driver, platform, tmp_path, sleeps) -> None:
    platform.refuse_parts = 2
    await send(driver, DATASET, [local(tmp_path, "a.bin", b"abcd")], parallel=1)
    assert platform.assembled["a.bin"] == b"abcd"
    assert len(platform.api_calls("POST")) == 1 + 3 + 1  # announce, one address for each of the three tries, complete
    assert len(sleeps) == 2


async def test_a_part_that_keeps_being_refused_stops_the_upload_and_keeps_what_arrived(
    driver, platform, tmp_path
) -> None:
    files = [local(tmp_path, "a.bin", b"abcdefgh")]  # two parts
    platform.refuse_parts = 3 * 10
    with pytest.raises(errors.UploadError, match="run it again"):
        await send(driver, DATASET, files, parallel=1)
    assert not platform.completed


async def test_running_it_again_goes_on_from_the_parts_that_are_there(driver, platform, tmp_path) -> None:
    data = b"0123456789ab"  # three parts of 4
    files = [local(tmp_path, "a.bin", data)]
    # First run: the storage takes the first part, then refuses everything.
    original = platform.storage

    taken = 0

    def flaky(request: httpx2.Request) -> httpx2.Response:
        nonlocal taken
        if request.method == "PUT":
            taken += 1
            if taken > 1:
                return httpx2.Response(500)
        return original(request)

    platform.storage = flaky  # type: ignore[method-assign]
    with pytest.raises(errors.UploadError):
        await send(driver, DATASET, files, parallel=1)
    platform.storage = original  # type: ignore[method-assign]
    assert len(platform.parts) == 1 and not platform.completed

    sent_before = len([c for c in platform.storage_calls if c[0] == "PUT"])
    await send(driver, DATASET, files, parallel=1)
    assert platform.assembled["a.bin"] == data
    assert len(platform.uploads) == 1  # the same upload, not a new one
    assert (
        len([c for c in platform.storage_calls if c[0] == "PUT"]) - sent_before == 2
    )  # the two parts that were missing


async def test_a_part_that_arrived_with_the_wrong_size_is_sent_again(driver, platform, tmp_path) -> None:
    files = [local(tmp_path, "a.bin", b"abcdefgh")]
    original = platform.storage
    platform.storage = lambda r: httpx2.Response(500) if r.method == "PUT" else original(r)  # type: ignore[method-assign]
    with pytest.raises(errors.UploadError):
        await send(driver, DATASET, files, parallel=1)
    platform.storage = original  # type: ignore[method-assign]
    upload_id = next(iter(platform.uploads))
    entry = platform.uploads[upload_id]["files"][0]
    platform.parts[(upload_id, entry["id"], 1)] = b"ab"  # cut short
    await send(driver, DATASET, files, parallel=1)
    assert platform.assembled["a.bin"] == b"abcdefgh"


async def test_a_file_that_changed_is_a_new_upload_not_a_wrong_resume(driver, platform, tmp_path) -> None:
    files = [local(tmp_path, "a.bin", b"abcdefgh")]
    platform.refuse_parts = 100
    with pytest.raises(errors.UploadError):
        await send(driver, DATASET, files, parallel=1)
    platform.refuse_parts = 0
    changed = [local(tmp_path, "a.bin", b"ABCDEFGHIJKL")]
    await send(driver, DATASET, changed)
    assert len(platform.uploads) == 2
    assert platform.assembled["a.bin"] == b"ABCDEFGHIJKL"


async def test_a_file_that_changes_while_it_is_being_sent_is_refused(driver, platform, tmp_path) -> None:
    file = local(tmp_path, "a.bin", b"abcdefgh")
    file.source.write_bytes(b"abc")  # another size than announced
    with pytest.raises(errors.FileChanged):
        await send(driver, DATASET, [file], fingerprint=False)
    assert not platform.completed


async def test_an_upload_that_the_server_forgot_is_announced_again(driver, platform, tmp_path) -> None:
    files = [local(tmp_path, "a.bin", b"abcdefgh")]
    platform.refuse_parts = 100
    with pytest.raises(errors.UploadError):
        await send(driver, DATASET, files, parallel=1)
    platform.refuse_parts = 0
    next(iter(platform.uploads.values()))["status"] = "aborted"  # expired, or given up elsewhere
    await send(driver, DATASET, files)
    assert len(platform.uploads) == 2 and platform.assembled["a.bin"] == b"abcdefgh"


async def test_the_state_is_forgotten_once_it_is_done(driver, platform, tmp_path) -> None:
    files = [local(tmp_path, "a.bin", b"abcdefgh")]
    await send(driver, DATASET, files)
    assert not list((tmp_path / "cache" / "uploads").glob("*.json"))
    await send(driver, DATASET, files)  # the same again is a new upload, not a resume of a finished one
    assert len(platform.uploads) == 2


async def test_only_a_few_parts_go_at_a_time(driver, platform, tmp_path) -> None:
    await send(driver, DATASET, [local(tmp_path, "a.bin", bytes(40))], parallel=2)  # ten parts
    assert 1 <= platform.most_running <= 2


async def test_a_wrong_token_stops_before_anything_is_sent(build, platform, tmp_path) -> None:
    d = build("sync", token="mh_wrong")
    with pytest.raises(errors.AuthenticationError):
        await d.call(upload, DATASET, [local(tmp_path, "a.bin", b"abcd")])
    assert not [r for r in platform.requests if r.url.host == "storage.test"]


async def test_an_upload_can_be_given_up(driver, platform, tmp_path) -> None:
    platform.refuse_parts = 100
    with pytest.raises(errors.UploadError):
        await send(driver, DATASET, [local(tmp_path, "a.bin", b"abcd")], parallel=1)
    upload_id = next(iter(platform.uploads))
    await driver.call(abort if driver.mode == "sync" else aabort, DATASET, upload_id)
    assert platform.uploads[upload_id]["status"] == "aborted"


async def test_both_clients_send_the_same_bytes(platform, tmp_path) -> None:
    """Running the two engines on the same files gives the same files on the platform."""
    from myhug import AsyncClient, Client
    from tests.fake import API

    data = bytes(range(37))
    a = local(tmp_path, "a.bin", data)
    with Client(API, token="mh_good", transport=httpx2.MockTransport(platform), cache_dir=tmp_path / "c1") as client:
        await asyncio.to_thread(upload, client, DATASET, [a])
    first = dict(platform.assembled)
    platform.assembled.clear()
    async with AsyncClient(
        API, token="mh_good", transport=httpx2.MockTransport(platform), cache_dir=tmp_path / "c2"
    ) as client:
        await aupload(client, DATASET, [a])
    assert platform.assembled == first == {"a.bin": data}
