from pathlib import Path

import httpx2
import pytest

from myhug import errors
from myhug._download import adownload, download
from myhug._transfer import Progress
from tests.fake import FakePlatform, sha

DATA = bytes(range(256)) * 20  # 5120 bytes


async def get(driver, route: str, dest: Path, **options) -> Path:
    return await driver.call(download if driver.mode == "sync" else adownload, route, dest, **options)


def storage_gets(platform: FakePlatform) -> list[dict]:
    return [headers for method, _, headers in platform.storage_calls if method == "GET"]


async def test_a_file_is_streamed_to_disk_and_checked(driver, platform: FakePlatform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    seen: list[Progress] = []
    path = await get(
        driver, "/api/files/a.bin", tmp_path / "out" / "a.bin", size=len(DATA), sha256=sha(DATA), progress=seen.append
    )
    assert path.read_bytes() == DATA
    assert seen[-1] == Progress(len(DATA), len(DATA), str(path))
    assert not (tmp_path / "out" / "a.bin.part").exists()
    assert "authorization" not in storage_gets(platform)[0]


async def test_a_file_without_known_size_or_fingerprint_is_downloaded_all_the_same(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    assert (await get(driver, "/api/files/a.bin", tmp_path / "a.bin")).read_bytes() == DATA


async def test_the_same_file_is_never_fetched_twice(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    await get(driver, "/api/files/a.bin", tmp_path / "one" / "a.bin", size=len(DATA), sha256=sha(DATA))
    assert len(storage_gets(platform)) == 1
    # Another folder, same content: it comes from the machine, the storage is not asked.
    second = await get(driver, "/api/files/a.bin", tmp_path / "two" / "a.bin", size=len(DATA), sha256=sha(DATA))
    assert second.read_bytes() == DATA and len(storage_gets(platform)) == 1


async def test_a_file_that_is_already_there_is_not_downloaded(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    dest = tmp_path / "a.bin"
    dest.write_bytes(DATA)
    await get(driver, "/api/files/a.bin", dest, size=len(DATA), sha256=sha(DATA))
    assert not storage_gets(platform) and not platform.api_calls()


async def test_a_file_with_the_same_size_but_other_content_is_replaced(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    dest = tmp_path / "a.bin"
    dest.write_bytes(bytes(len(DATA)))
    await get(driver, "/api/files/a.bin", dest, size=len(DATA), sha256=sha(DATA))
    assert dest.read_bytes() == DATA


async def test_an_interrupted_download_goes_on_from_where_it_stopped(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    dest = tmp_path / "a.bin"
    (tmp_path / "a.bin.part").write_bytes(DATA[:1000])  # what a previous run left
    await get(driver, "/api/files/a.bin", dest, size=len(DATA), sha256=sha(DATA))
    assert dest.read_bytes() == DATA
    assert storage_gets(platform)[0]["range"] == "bytes=1000-"


async def test_a_connection_that_drops_in_the_middle_is_resumed_by_itself(driver, platform, tmp_path, sleeps) -> None:
    platform.files["a.bin"] = DATA
    platform.break_after = 2000
    dest = await get(driver, "/api/files/a.bin", tmp_path / "a.bin", size=len(DATA), sha256=sha(DATA))
    assert dest.read_bytes() == DATA
    ranges = [h.get("range") for h in storage_gets(platform)]
    assert ranges == [None, "bytes=2000-"] and len(sleeps) == 1


async def test_a_storage_that_does_not_do_ranges_starts_again_from_the_beginning(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    platform.honour_range = False
    (tmp_path / "a.bin.part").write_bytes(DATA[:1000])
    dest = await get(driver, "/api/files/a.bin", tmp_path / "a.bin", size=len(DATA), sha256=sha(DATA))
    assert dest.read_bytes() == DATA  # not the first 1000 bytes twice


async def test_a_leftover_longer_than_the_file_is_thrown_away(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    (tmp_path / "a.bin.part").write_bytes(bytes(len(DATA) + 50))
    dest = await get(driver, "/api/files/a.bin", tmp_path / "a.bin", size=len(DATA), sha256=sha(DATA))
    assert dest.read_bytes() == DATA


async def test_a_download_that_is_not_the_file_is_not_kept(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    with pytest.raises(errors.IntegrityError):
        await get(driver, "/api/files/a.bin", tmp_path / "a.bin", size=len(DATA), sha256=sha(b"something else"))
    assert not (tmp_path / "a.bin").exists() and not (tmp_path / "a.bin.part").exists()


async def test_a_file_of_another_size_is_not_kept(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    with pytest.raises(errors.IntegrityError):
        await get(driver, "/api/files/a.bin", tmp_path / "a.bin", size=len(DATA) + 1)
    assert not (tmp_path / "a.bin").exists()


async def test_a_wrong_download_does_not_enter_the_local_copy(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    with pytest.raises(errors.IntegrityError):
        await get(driver, "/api/files/a.bin", tmp_path / "a.bin", sha256=sha(b"x"))
    platform.files["a.bin"] = DATA  # the platform is right this time
    await get(driver, "/api/files/a.bin", tmp_path / "b.bin", sha256=sha(DATA))
    assert (tmp_path / "b.bin").read_bytes() == DATA


async def test_an_address_that_expired_is_asked_for_again(driver, platform, tmp_path, sleeps) -> None:
    platform.files["a.bin"] = DATA
    platform.refuse_gets = 1
    dest = await get(driver, "/api/files/a.bin", tmp_path / "a.bin", size=len(DATA))
    assert dest.read_bytes() == DATA
    assert len(platform.api_calls("GET", "/api/files/a.bin")) == 2  # a fresh address


async def test_a_storage_that_keeps_refusing_is_an_error(driver, platform, tmp_path) -> None:
    platform.files["a.bin"] = DATA
    platform.refuse_gets = 100
    with pytest.raises(errors.ApiError, match="refused"):
        await get(driver, "/api/files/a.bin", tmp_path / "a.bin")


async def test_a_file_that_does_not_exist_is_not_found(driver, platform, tmp_path) -> None:
    with pytest.raises(errors.NotFound):
        await get(driver, "/api/files/nothing.bin", tmp_path / "a.bin")


async def test_an_api_that_does_not_redirect_is_an_error(driver, platform, tmp_path) -> None:
    with pytest.raises(errors.ApiError, match="did not give an address"):
        await get(driver, "/api/nowhere", tmp_path / "a.bin")


async def test_a_connection_that_never_comes_back_says_to_run_it_again(build, platform, tmp_path, sleeps) -> None:
    platform.files["a.bin"] = DATA
    original = platform.storage

    def always_breaking(request: httpx2.Request) -> httpx2.Response:
        platform.break_after = 100
        return original(request)

    platform.storage = always_breaking  # type: ignore[method-assign]
    d = build("sync")
    with pytest.raises(errors.ConnectionFailed, match="run it again"):
        await d.call(download, "/api/files/a.bin", tmp_path / "a.bin", size=len(DATA))
    assert (tmp_path / "a.bin.part").exists()  # what arrived is kept for the next run
