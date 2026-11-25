import pytest

from myhug import errors
from myhug._models import CodeIn
from tests.fake import FakePlatform
from tests.helpers import get, run

WEIGHTS = b"0123456789abcdef"


async def open_model(
    driver, platform: FakePlatform, files: dict[str, bytes] | None = None, address: str = "ada/sentiment"
):
    platform.catalog.add("models", address, files)
    return await get(driver, "models", address)


# ---- the model itself


async def test_a_model_is_got_changed_liked_and_deleted(driver, platform) -> None:
    model = await open_model(driver, platform, {"w.bin": WEIGHTS})
    assert model.address == "ada/sentiment" and model.info.version == 1
    await run(driver, model.update, license="mit", parameters=7)
    assert model.info.license == "mit" and model.info.parameters == 7
    assert await run(driver, model.like) == 1
    assert await run(driver, model.unlike) == 0
    await run(driver, model.delete)
    with pytest.raises(errors.NotFound):
        await get(driver, "models", "ada/sentiment")


async def test_a_model_is_created_with_its_tasks_and_inputs(driver, platform) -> None:
    model = await run(driver, driver.client.models.create, "ner", tasks=["ner"], inputs=["text"], license="mit")
    assert platform.catalog.created == [{"name": "ner", "tasks": ["ner"], "inputs": ["text"], "license": "mit"}]
    assert model.address == "ada/ner"


async def test_the_people_with_access_are_listed_added_and_taken_away(driver, platform) -> None:
    model = await open_model(driver, platform)
    assert await run(driver, model.members) == []
    assert (await run(driver, model.set_member, "u2", "maintainer")).role == "maintainer"
    assert [m.user_id for m in await run(driver, model.members)] == ["u2"]
    await run(driver, model.remove_member, "u2")
    assert await run(driver, model.members) == []


async def test_where_a_model_is_served_is_said_read_and_removed(driver, platform) -> None:
    model = await open_model(driver, platform)
    done = await run(
        driver,
        model.set_endpoint,
        kind="mlflow",
        url="http://mlflow-serving:5001",
        input_kind="text",
        output_kind="labels",
    )
    assert done.kind.value == "mlflow" and done.has_auth is False
    assert (await run(driver, model.endpoint)).url == "http://mlflow-serving:5001"
    await run(driver, model.remove_endpoint)
    with pytest.raises(errors.NotFound):
        await run(driver, model.endpoint)


async def test_a_model_is_tried_and_the_call_is_not_repeated_if_it_fails(driver, platform) -> None:
    model = await open_model(driver, platform)
    answer = await run(driver, model.predict, {"text": "great"})
    assert answer.output == {"echo": {"text": "great"}} and answer.took_ms == 3
    assert platform.catalog.predictions == [{"text": "great"}]


async def test_a_model_that_is_not_served_is_a_conflict_that_is_not_tried_again(driver, platform) -> None:
    import httpx2

    model = await open_model(driver, platform)
    platform.say("POST", "/api/models/ada/sentiment/predict", httpx2.Response(503, json={"detail": "down"}))
    with pytest.raises(errors.ServerError):
        await run(driver, model.predict, "x")
    assert len(platform.api_calls("POST", "/api/models/ada/sentiment/predict")) == 1


# ---- versions and files


async def test_the_versions_come_newest_first_and_one_has_its_files(driver, platform) -> None:
    model = await open_model(driver, platform, {"w.bin": WEIGHTS})
    platform.catalog.new_version(
        platform.catalog.entities[("models", "ada/sentiment")], {"w.bin": WEIGHTS, "c.json": b"{}"}
    )
    assert [v.number for v in await run(driver, model.versions)] == [2, 1]
    assert [f.path for f in (await run(driver, model.version)).files] == ["c.json", "w.bin"]  # the latest
    assert [f.path for f in await run(driver, model.files, 1)] == ["w.bin"]


async def test_a_model_with_no_version_says_so(driver, platform) -> None:
    model = await open_model(driver, platform)
    with pytest.raises(ValueError, match="no version"):
        await run(driver, model.version)


async def test_the_files_of_a_version_are_downloaded_with_their_path(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform, {"weights/w.bin": WEIGHTS, "config.json": b"{}"})
    paths = await run(driver, model.download, tmp_path / "out")
    assert sorted(p.relative_to(tmp_path / "out").as_posix() for p in paths) == ["config.json", "weights/w.bin"]
    assert (tmp_path / "out" / "weights" / "w.bin").read_bytes() == WEIGHTS
    assert {r.url.params["version"] for r in platform.api_calls("GET") if "/files/" in r.url.path} == {"1"}


async def test_one_file_of_one_version_is_downloaded(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform, {"a.bin": b"one", "b.bin": b"two"})
    paths = await run(driver, model.download, tmp_path / "out", path="b.bin", version=1)
    assert [p.name for p in paths] == ["b.bin"]
    with pytest.raises(ValueError, match="No file"):
        await run(driver, model.download, tmp_path / "out", path="c.bin")


async def test_the_files_of_a_version_go_to_the_cache_of_the_sdk_by_default(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform, {"a.bin": b"one"})
    paths = await run(driver, model.download)
    assert paths == [(tmp_path / "cache" / "models" / "ada" / "sentiment" / "1" / "a.bin").resolve()]


async def test_a_version_is_deleted(driver, platform) -> None:
    model = await open_model(driver, platform, {"w.bin": WEIGHTS})
    platform.catalog.new_version(platform.catalog.entities[("models", "ada/sentiment")], {"w.bin": WEIGHTS})
    await run(driver, model.delete_version, 2)
    assert [v.number for v in await run(driver, model.versions)] == [1]


# ---- new versions


async def test_files_and_a_reference_to_code_make_one_version(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform)
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(WEIGHTS)
    code = {"url": "https://github.com/o/r", "ref": "main", "path": "src"}
    version = await run(driver, model.upload_version, [weights], code=code, message="first")
    assert version.number == 1 and version.code.url == "https://github.com/o/r" and version.code.state == "unresolved"
    assert platform.announced[-1]["code"] == code and platform.announced[-1]["message"] == "first"
    assert platform.catalog.entities[("models", "ada/sentiment")].latest()["files"] == {"model.safetensors": WEIGHTS}


async def test_a_code_reference_may_be_given_as_a_model_of_the_api(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform)
    weights = tmp_path / "w.bin"
    weights.write_bytes(WEIGHTS)
    await run(driver, model.upload_version, [weights], code=CodeIn(url="https://github.com/o/r", ref="v1"))
    assert platform.announced[-1]["code"] == {
        "url": "https://github.com/o/r",
        "ref": "v1",
    }  # what is not set is not sent


async def test_a_folder_is_a_version_with_the_paths_it_has(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform)
    (tmp_path / "m" / "tokenizer").mkdir(parents=True)
    (tmp_path / "m" / "w.bin").write_bytes(WEIGHTS)
    (tmp_path / "m" / "tokenizer" / "t.json").write_bytes(b"{}")
    await run(driver, model.upload_version, folder=tmp_path / "m")
    assert sorted(platform.catalog.entities[("models", "ada/sentiment")].latest()["files"]) == [
        "tokenizer/t.json",
        "w.bin",
    ]


async def test_a_version_that_is_only_code_uploads_nothing(driver, platform) -> None:
    model = await open_model(driver, platform, {"w.bin": WEIGHTS})
    version = await run(driver, model.upload_version, code={"url": "https://github.com/o/r"}, message="code only")
    assert version.number == 2 and version.message == "code only"
    assert not platform.uploads and not [r for r in platform.requests if r.url.host == "storage.test"]
    assert platform.catalog.entities[("models", "ada/sentiment")].latest()["files"] == {"w.bin": WEIGHTS}  # inherited


async def test_code_alone_is_also_made_directly(driver, platform) -> None:
    model = await open_model(driver, platform)
    version = await run(driver, model.create_code_version, {"url": "https://github.com/o/r", "ref": "abc"}, message="m")
    assert version.number == 1 and version.code.ref == "abc"
    assert platform.api_calls("POST", "/api/models/ada/sentiment/versions")[0].content  # a POST is not made twice
    assert len(platform.api_calls("POST", "/api/models/ada/sentiment/versions")) == 1


async def test_a_version_needs_files_code_or_something_to_remove(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform)
    with pytest.raises(ValueError, match="needs files"):
        await run(driver, model.upload_version)
    with pytest.raises(ValueError, match="is not a file"):
        await run(driver, model.upload_version, [tmp_path / "nothing.bin"])


async def test_paths_can_be_taken_out_of_the_latest_version(driver, platform) -> None:
    model = await open_model(driver, platform, {"old.bin": b"old", "keep.bin": b"keep"})
    version = await run(driver, model.upload_version, remove=["old.bin"])
    assert version.number == 2
    assert platform.catalog.entities[("models", "ada/sentiment")].latest()["files"] == {"keep.bin": b"keep"}


async def test_a_file_the_platform_already_holds_is_not_sent_again(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform, {"w.bin": WEIGHTS})
    from tests.fake import sha

    platform.held.add(sha(WEIGHTS))
    weights = tmp_path / "w.bin"
    weights.write_bytes(WEIGHTS)
    await run(driver, model.upload_version, [weights], message="same weights, new message")
    assert not [r for r in platform.requests if r.url.host == "storage.test" and r.method == "PUT"]


async def test_a_version_can_be_waited_for_while_it_is_made(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform)
    weights = tmp_path / "w.bin"
    weights.write_bytes(WEIGHTS)
    original = platform.catalog.completed

    def settled(*args, **kwargs):
        version = original(*args, **kwargs)
        version["status"] = "ready"
        return version

    platform.catalog.completed = settled  # type: ignore[method-assign]
    assert (await run(driver, model.upload_version, [weights], wait=True)).status == "ready"


async def test_wait_says_why_a_version_failed_and_gives_up_after_its_timeout(driver, platform, sleeps) -> None:
    entity = platform.catalog.add("models", "ada/sentiment", {"w.bin": WEIGHTS}, status="failed")
    entity.latest()["error"] = "The file is not a model"
    model = await get(driver, "models", "ada/sentiment")
    with pytest.raises(errors.VersionFailed, match="not a model"):
        await run(driver, model.wait)
    entity.latest()["status"] = "pending"
    with pytest.raises(errors.WaitTimeout):
        await run(driver, model.wait, timeout=4)
    assert sleeps == [2.0, 2.0]
