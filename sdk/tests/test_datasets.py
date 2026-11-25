from pathlib import Path

import pytest

from myhug import errors
from tests.fake import FakePlatform
from tests.helpers import collect, commit, get, run

TRAIN = b"id,label,score\n1,pos,0.5\n2,neg,0.25\n"
TEST = b"id,label,score\n3,pos,1\n"


@pytest.fixture
def dataset_files() -> dict[str, bytes]:
    return {"data/train.csv": TRAIN, "data/test.csv": TEST, "README.md": b"# readme\n"}


async def open_dataset(driver, platform: FakePlatform, files: dict[str, bytes] | None, address: str = "ada/sentiment"):
    platform.catalog.add("datasets", address, files)
    return await get(driver, "datasets", address)


# ---- the dataset itself


async def test_a_dataset_is_got_by_its_address_and_shows_its_splits(driver, platform, dataset_files) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    assert dataset.address == "ada/sentiment" and dataset.info.version == 1
    assert dataset.splits == ["test", "train"]


async def test_a_wrong_address_is_refused_before_any_call(driver, platform) -> None:
    for address in ("sentiment", "a/b/c", "/x", "a/"):
        with pytest.raises(ValueError, match="owner/name"):
            await get(driver, "datasets", address)
    assert not platform.requests


async def test_a_dataset_that_does_not_exist_is_not_found(driver, platform) -> None:
    with pytest.raises(errors.NotFound):
        await get(driver, "datasets", "ada/nothing")


async def test_a_dataset_is_changed_liked_and_deleted(driver, platform, dataset_files) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    await run(driver, dataset.update, description="Reviews", tags=["nlp"])
    assert dataset.info.description == "Reviews" and dataset.info.tags == ["nlp"]
    assert await run(driver, dataset.like) == 1
    assert await run(driver, dataset.unlike) == 0
    await run(driver, dataset.delete)
    with pytest.raises(errors.NotFound):
        await get(driver, "datasets", "ada/sentiment")


async def test_a_dataset_is_created_in_my_name(driver, platform) -> None:
    resources = driver.client.datasets
    dataset = await run(driver, resources.create, "reviews", modality="text", tags=["nlp"], visibility="private")
    assert platform.catalog.created == [
        {"name": "reviews", "modality": "text", "tags": ["nlp"], "visibility": "private"}
    ]
    assert dataset.address == "ada/reviews" and dataset.info.tags == ["nlp"]


# ---- files and splits


async def test_the_files_of_a_split_are_those_of_that_split(driver, platform, dataset_files) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    assert [f.path for f in await run(driver, dataset.files)] == ["README.md", "data/test.csv", "data/train.csv"]
    assert [f.path for f in await run(driver, dataset.files, split="train")] == ["data/train.csv"]


async def test_an_unknown_split_says_which_ones_there_are(driver, platform, dataset_files) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    with pytest.raises(ValueError, match="test, train"):
        await run(driver, dataset.files, split="dev")


async def test_the_listing_and_the_downloads_are_of_the_same_version(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    await run(driver, dataset.download, tmp_path / "out")
    versions = {r.url.params.get("version") for r in platform.api_calls("GET") if "/files" in r.url.path}
    assert versions == {"1"}  # asked as a number, never as "the latest"


# ---- download


async def test_everything_is_downloaded_with_its_path(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    paths = await run(driver, dataset.download, tmp_path / "out")
    assert sorted(p.relative_to(tmp_path / "out").as_posix() for p in paths) == [
        "README.md",
        "data/test.csv",
        "data/train.csv",
    ]
    assert (tmp_path / "out" / "data" / "train.csv").read_bytes() == TRAIN


async def test_one_split_or_one_file_is_downloaded(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    assert [p.name for p in await run(driver, dataset.download, tmp_path / "a", split="test")] == ["test.csv"]
    assert [p.name for p in await run(driver, dataset.download, tmp_path / "b", path="README.md")] == ["README.md"]
    assert not (tmp_path / "a" / "data" / "train.csv").exists()
    with pytest.raises(ValueError, match="No file"):
        await run(driver, dataset.download, tmp_path / "c", path="nothing.csv")


async def test_without_a_folder_the_files_go_to_the_cache_of_the_sdk(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    paths = await run(driver, dataset.download, split="train")
    assert paths[0] == (tmp_path / "cache" / "datasets" / "ada" / "sentiment" / "1" / "data" / "train.csv").resolve()


async def test_a_second_download_does_not_touch_the_storage(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    await run(driver, dataset.download, tmp_path / "out")
    before = len([c for c in platform.storage_calls if c[0] == "GET"])
    await run(driver, dataset.download, tmp_path / "out")
    assert len([c for c in platform.storage_calls if c[0] == "GET"]) == before


async def test_a_path_that_would_leave_the_folder_is_refused(driver, platform, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, {"../../evil.txt": b"x"})
    with pytest.raises(ValueError, match="not a path"):
        await run(driver, dataset.download, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


async def test_a_dataset_with_no_version_has_nothing_to_download(driver, platform, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, None)
    with pytest.raises(ValueError, match="no version"):
        await run(driver, dataset.download, tmp_path / "out")


# ---- rows


async def test_the_rows_of_the_train_split_are_typed_like_the_preview(driver, platform, dataset_files) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    rows = await collect(driver, dataset.iter_rows)
    assert rows == [{"id": 1, "label": "pos", "score": 0.5}, {"id": 2, "label": "neg", "score": 0.25}]


async def test_another_split_is_asked_by_its_name(driver, platform, dataset_files) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    rows = await collect(driver, lambda: dataset.iter_rows("test"))
    assert rows == [{"id": 3, "label": "pos", "score": 1}]


async def test_the_rows_of_the_files_of_a_split_follow_each_other(driver, platform) -> None:
    files = {"train-1.csv": b"a\n1\n2\n", "train-2.csv": b"a\n3\n"}
    dataset = await open_dataset(driver, platform, files)
    assert [r["a"] for r in await collect(driver, lambda: dataset.iter_rows("train"))] == [1, 2, 3]


async def test_streaming_reads_from_the_storage_and_keeps_nothing(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    rows = await collect(driver, lambda: dataset.iter_rows("train", streaming=True))
    assert len(rows) == 2 and rows[0]["label"] == "pos"
    assert not (tmp_path / "cache" / "datasets").exists()  # nothing was written
    assert [h.get("accept-encoding") for _, _, h in platform.storage_calls] == ["identity"]


async def test_streaming_gives_the_same_rows_as_a_download(driver, platform) -> None:
    text = b'id,text\n1,"a, b"\n2,"two\nlines"\n3,\n'
    dataset = await open_dataset(driver, platform, {"train.csv": text})
    streamed = await collect(driver, lambda: dataset.iter_rows(streaming=True))
    saved = await collect(driver, lambda: dataset.iter_rows())
    assert (
        streamed
        == saved
        == [
            {"id": 1, "text": "a, b"},
            {"id": 2, "text": "two\nlines"},
            {"id": 3, "text": None},
        ]
    )


async def test_jsonl_rows_are_the_objects_and_blank_lines_are_skipped(driver, platform) -> None:
    data = b'{"text": "a", "n": 1}\n\n{"text": "b", "tags": ["x"]}\n'
    dataset = await open_dataset(driver, platform, {"train.jsonl": data})
    expected = [{"text": "a", "n": 1}, {"text": "b", "tags": ["x"]}]
    assert await collect(driver, lambda: dataset.iter_rows()) == expected
    assert await collect(driver, lambda: dataset.iter_rows(streaming=True)) == expected


async def test_tsv_and_a_byte_order_mark(driver, platform) -> None:
    dataset = await open_dataset(driver, platform, {"train.tsv": "﻿a\tb\n1\ttrue\n".encode()})
    assert await collect(driver, lambda: dataset.iter_rows()) == [{"a": 1, "b": True}]
    assert await collect(driver, lambda: dataset.iter_rows(streaming=True)) == [{"a": 1, "b": True}]


async def test_a_short_line_is_completed_and_a_long_one_is_cut(driver, platform) -> None:
    dataset = await open_dataset(driver, platform, {"train.csv": b"a,b\n1\n2,3,4\n"})
    assert await collect(driver, lambda: dataset.iter_rows()) == [{"a": 1, "b": None}, {"a": 2, "b": 3}]


async def test_parquet_rows_are_read(driver, platform, tmp_path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "t.parquet"
    pq.write_table(pa.table({"id": [1, 2], "text": ["a", None]}), path)
    dataset = await open_dataset(driver, platform, {"train.parquet": path.read_bytes()})
    expected = [{"id": 1, "text": "a"}, {"id": 2, "text": None}]
    assert await collect(driver, lambda: dataset.iter_rows()) == expected
    # A Parquet file is always downloaded first: it is read by ranges of the file, not from start to end.
    assert await collect(driver, lambda: dataset.iter_rows(streaming=True)) == expected


async def test_a_file_that_is_not_what_its_name_says_is_an_error(driver, platform) -> None:
    bad_json = await open_dataset(driver, platform, {"train.jsonl": b'{"a": 1}\nnot json\n'}, "ada/one")
    with pytest.raises(errors.UnreadableRows, match="line 2 is not JSON"):
        await collect(driver, lambda: bad_json.iter_rows())
    not_utf8 = await open_dataset(driver, platform, {"train.csv": b"a\n\xff\xfe\n"}, "ada/two")
    with pytest.raises(errors.UnreadableRows, match="UTF-8"):
        await collect(driver, lambda: not_utf8.iter_rows(streaming=True))
    not_object = await open_dataset(driver, platform, {"train.jsonl": b"[1, 2]\n"}, "ada/three")
    with pytest.raises(errors.UnreadableRows, match="not a JSON object"):
        await collect(driver, lambda: not_object.iter_rows())
    open_quote = await open_dataset(driver, platform, {"train.csv": b'a\n"never closed\n'}, "ada/four")
    with pytest.raises(errors.UnreadableRows, match="quoted cell"):
        await collect(driver, lambda: open_quote.iter_rows())
    not_parquet = await open_dataset(driver, platform, {"train.parquet": b"not parquet"}, "ada/five")
    with pytest.raises(errors.UnreadableRows, match="Parquet"):
        await collect(driver, lambda: not_parquet.iter_rows())


async def test_a_dataset_without_rows_to_read_says_so(driver, platform) -> None:
    dataset = await open_dataset(driver, platform, {"image.png": b"x"})
    with pytest.raises(errors.UnsupportedFormat, match="no csv, tsv, jsonl or parquet"):
        await collect(driver, lambda: dataset.iter_rows())


async def test_rows_are_read_as_they_come(driver, platform) -> None:
    rows = b"a\n" + b"".join(b"%d\n" % i for i in range(5000))
    dataset = await open_dataset(driver, platform, {"train.csv": rows})
    if driver.mode == "sync":
        stream = dataset.iter_rows(streaming=True)
        assert next(stream) == {"a": 0}
        stream.close()
    else:
        stream = dataset.iter_rows(streaming=True)
        assert await anext(stream) == {"a": 0}
        await stream.aclose()


# ---- new versions


async def test_a_version_adds_replaces_and_removes(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    new = tmp_path / "new.csv"
    new.write_bytes(b"id\n9\n")
    version = await commit(
        driver, dataset, {"data/extra.csv": new, "data/train.csv": new}, ("README.md",), message="rework"
    )
    assert version.number == 2 and version.message == "rework" and version.status == "pending"
    entity = platform.catalog.entities[("datasets", "ada/sentiment")]
    assert sorted(entity.latest()["files"]) == [
        "data/extra.csv",
        "data/test.csv",
        "data/train.csv",
    ]  # test.csv inherited
    assert entity.latest()["files"]["data/train.csv"] == b"id\n9\n"  # replaced
    assert platform.announced[-1]["remove"] == ["README.md"]
    assert dataset.info.version == 2  # the dataset was read again


async def test_a_block_that_fails_sends_nothing(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    source = tmp_path / "f.csv"
    source.write_bytes(b"a\n")

    class Boom(Exception):
        pass

    if driver.mode == "sync":

        def blocking() -> None:
            with dataset.new_version() as version:
                version.add(source)
                raise Boom

        with pytest.raises(Boom):
            await run(driver, blocking)
    else:
        with pytest.raises(Boom):
            async with dataset.new_version() as version:
                version.add(source)
                raise Boom
    assert not platform.uploads and dataset.info.version == 1


async def test_a_version_needs_something_and_not_a_path_both_added_and_removed(
    driver, platform, dataset_files, tmp_path
) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    with pytest.raises(ValueError, match="Nothing to commit"):
        await commit(driver, dataset)
    source = tmp_path / "f.csv"
    source.write_bytes(b"a\n")
    with pytest.raises(ValueError, match="both added and removed"):
        await commit(driver, dataset, {"x.csv": source}, ("x.csv",))
    with pytest.raises(ValueError, match="is not a file"):
        await commit(driver, dataset, {"x.csv": tmp_path / "nothing"})
    assert not platform.uploads


@pytest.mark.parametrize("path", ["../x.csv", "/abs.csv", "a/../../x", "."])
async def test_a_path_outside_the_version_is_refused(driver, platform, dataset_files, tmp_path, path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    source = tmp_path / "f.csv"
    source.write_bytes(b"a\n")
    with pytest.raises(ValueError, match="not a path inside a version"):
        await commit(driver, dataset, {path: source})


async def test_upload_file_is_one_file_one_version(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    source = tmp_path / "local-name.csv"
    source.write_bytes(b"a\n1\n")
    version = await run(driver, dataset.upload_file, source, "data/valid.csv", message="one")
    assert version.number == 2
    assert platform.catalog.entities[("datasets", "ada/sentiment")].latest()["files"]["data/valid.csv"] == b"a\n1\n"


# ---- a folder


def folder(tmp_path: Path, files: dict[str, bytes]) -> Path:
    root = tmp_path / "work"
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    return root


async def test_a_folder_becomes_the_first_version(driver, platform, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, None)
    root = folder(tmp_path, {"data/train.csv": TRAIN, "README.md": b"hi"})
    version = await run(driver, dataset.upload_folder, root, message="first")
    assert version.number == 1
    assert platform.catalog.entities[("datasets", "ada/sentiment")].latest()["files"] == {
        "data/train.csv": TRAIN,
        "README.md": b"hi",
    }


async def test_the_same_folder_again_makes_no_version(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    root = folder(tmp_path, dataset_files)
    assert await run(driver, dataset.upload_folder, root) is None
    assert not platform.uploads  # not even announced


async def test_only_what_changed_is_sent_and_nothing_is_removed_unless_asked(
    driver, platform, dataset_files, tmp_path
) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    root = folder(tmp_path, {"data/train.csv": TRAIN + b"4,pos,1\n", "data/test.csv": TEST, "new.csv": b"a\n"})
    (root / "README.md").unlink(missing_ok=True)
    version = await run(driver, dataset.upload_folder, root, message="sync")
    assert version.number == 2
    assert sorted(f["path"] for f in platform.announced[-1]["files"]) == [
        "data/train.csv",
        "new.csv",
    ]  # test.csv is not
    assert platform.announced[-1]["remove"] == []
    assert "README.md" in platform.catalog.entities[("datasets", "ada/sentiment")].latest()["files"]  # kept


async def test_delete_takes_out_what_the_folder_no_longer_has(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    root = folder(tmp_path, {"data/train.csv": TRAIN, "data/test.csv": TEST})
    version = await run(driver, dataset.upload_folder, root, delete=True)
    assert (
        version.number == 2
        and platform.announced[-1]["remove"] == ["README.md"]
        and platform.announced[-1]["files"] == []
    )
    assert sorted(platform.catalog.entities[("datasets", "ada/sentiment")].latest()["files"]) == [
        "data/test.csv",
        "data/train.csv",
    ]


async def test_a_folder_is_not_sent_with_what_is_ignored(driver, platform, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, None)
    root = folder(
        tmp_path, {"a.csv": b"a\n", ".git/config": b"x", "x/.DS_Store": b"x", "__pycache__/m.pyc": b"x", "b.part": b"x"}
    )
    await run(driver, dataset.upload_folder, root)
    assert [f["path"] for f in platform.announced[-1]["files"]] == ["a.csv"]
    await run(
        driver, dataset.upload_folder, root, ignore=["a.csv"], prefix="extra"
    )  # what is ignored is the caller's choice
    assert sorted(f["path"] for f in platform.announced[-1]["files"]) == [
        "extra/.git/config",
        "extra/__pycache__/m.pyc",
        "extra/b.part",
        "extra/x/.DS_Store",
    ]


async def test_a_prefix_keeps_the_sync_inside_its_folder(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    root = folder(tmp_path, {"a.csv": b"a\n"})
    await run(driver, dataset.upload_folder, root, prefix="extra", delete=True)
    assert platform.announced[-1]["remove"] == []  # the files outside `extra/` are not touched
    assert [f["path"] for f in platform.announced[-1]["files"]] == ["extra/a.csv"]


async def test_a_file_whose_fingerprint_the_platform_does_not_know_yet_is_sent_again(
    driver, platform, tmp_path
) -> None:
    dataset = await open_dataset(driver, platform, {"a.csv": b"a\n"})
    platform.catalog.entities[("datasets", "ada/sentiment")].latest()["fingerprinted"] = False
    root = folder(tmp_path, {"a.csv": b"a\n"})
    version = await run(driver, dataset.upload_folder, root)
    assert version is not None and version.number == 2


async def test_a_folder_that_is_not_one_is_refused(driver, platform, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, None)
    with pytest.raises(ValueError, match="is not a folder"):
        await run(driver, dataset.upload_folder, tmp_path / "nothing")


# ---- waiting for the platform


async def test_wait_returns_when_the_version_is_ready(build, platform, dataset_files, sleeps) -> None:
    for mode in ("sync", "async"):
        d = build(mode)
        sleeps.clear()
        entity = platform.catalog.add("datasets", "ada/sentiment", dataset_files, status="pending")

        class Settling(list):
            def append(self, item: float, entity=entity) -> None:  # the platform reads the files while the SDK waits
                super().append(item)
                if len(self) == 2:
                    entity.latest()["status"] = "ready"

        d.client._sleep = Settling().append if mode == "sync" else _async_append(Settling())  # type: ignore[assignment]
        dataset = await get(d, "datasets", "ada/sentiment")
        version = await run(d, dataset.wait)
        assert version.status == "ready"


def _async_append(target: list):
    async def sleep(seconds: float) -> None:
        target.append(seconds)

    return sleep


async def test_wait_raises_when_the_platform_could_not_read_the_version(driver, platform, dataset_files) -> None:
    entity = platform.catalog.add("datasets", "ada/sentiment", dataset_files, status="failed")
    entity.latest()["error"] = "The file is not a table"
    dataset = await get(driver, "datasets", "ada/sentiment")
    with pytest.raises(errors.VersionFailed, match="not a table") as raised:
        await run(driver, dataset.wait)
    assert raised.value.number == 1 and raised.value.reason == "The file is not a table"


async def test_wait_gives_up_after_its_timeout(driver, platform, dataset_files, sleeps) -> None:
    platform.catalog.add("datasets", "ada/sentiment", dataset_files, status="pending")
    dataset = await get(driver, "datasets", "ada/sentiment")
    with pytest.raises(errors.WaitTimeout, match="still being read"):
        await run(driver, dataset.wait, timeout=6)
    assert sleeps == [2.0, 2.0, 2.0]


async def test_a_version_can_be_waited_for_as_it_is_made(driver, platform, dataset_files, tmp_path) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    source = tmp_path / "f.csv"
    source.write_bytes(b"a\n")
    entity = platform.catalog.entities[("datasets", "ada/sentiment")]
    original = platform.catalog.completed

    def complete_and_settle(*args, **kwargs):
        version = original(*args, **kwargs)
        version["status"] = "ready"  # the worker was quick
        return version

    platform.catalog.completed = complete_and_settle  # type: ignore[method-assign]
    version = await commit(driver, dataset, {"f.csv": source}, wait=True)
    assert version.status == "ready" and entity.latest()["number"] == 2


# ---- who has access


async def test_the_people_with_access_are_listed_added_and_taken_away(driver, platform, dataset_files) -> None:
    dataset = await open_dataset(driver, platform, dataset_files)
    assert await run(driver, dataset.members) == []
    assert (await run(driver, dataset.set_member, "u2", "annotator")).role == "annotator"
    await run(driver, dataset.set_member, "u3", "reader")
    assert sorted((m.user_id, m.role) for m in await run(driver, dataset.members)) == [
        ("u2", "annotator"),
        ("u3", "reader"),
    ]
    await run(driver, dataset.remove_member, "u2")
    assert [m.user_id for m in await run(driver, dataset.members)] == ["u3"]
