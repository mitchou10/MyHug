import uuid

import httpx2
import pytest

from tests.conftest import CSV, KEY, FakePlatform, sha256
from worker import tasks
from worker.celery_app import celery_app


def run(version: uuid.UUID | None = None):
    return tasks.process_version.apply(args=[str(version or uuid.uuid4())])


def test_a_version_is_read_and_the_api_is_told(platform: FakePlatform) -> None:
    platform.to_read = [platform.add_file("train.csv", CSV)]
    result = run()
    assert result.successful() and result.result == "ready"
    (found,) = platform.bodies[next(path for path in platform.bodies if path.endswith("/result"))]["files"]
    assert found["size_bytes"] == len(CSV)
    assert found["sha256"] == sha256(CSV)
    assert found["rows"] == 3 and found["columns"] == [{"name": "n", "dtype": "int"}]


def test_only_what_the_api_asks_for_is_computed(platform: FakePlatform) -> None:
    platform.to_read = [
        platform.add_file("train.csv", CSV, fingerprint=False),
        platform.add_file("model.bin", b"\x00\x01", rows=False),
    ]
    run()
    csv_file, other = platform.bodies[next(path for path in platform.bodies if path.endswith("/result"))]["files"]
    assert "sha256" not in csv_file and csv_file["rows"] == 3
    assert other["sha256"] == sha256(b"\x00\x01") and "rows" not in other


def test_there_is_nothing_to_do_when_the_version_is_not_up_for_the_taking(platform: FakePlatform) -> None:
    platform.to_read = None
    assert run().result is None
    assert [method for method, _ in platform.calls] == ["POST"]  # it claimed, and that was all


def test_a_file_that_cannot_be_read_fails_the_version_with_the_reason(platform: FakePlatform) -> None:
    platform.to_read = [platform.add_file("bad.parquet", b"nope")]
    assert run().result == "failed"
    body = platform.bodies[next(path for path in platform.bodies if path.endswith("/failure"))]
    assert "bad.parquet" in body["error"]


def test_a_file_missing_from_the_storage_fails_the_version(platform: FakePlatform) -> None:
    gone = platform.add_file("train.csv", CSV)
    del platform.files[gone["url"]]
    platform.to_read = [gone]
    assert run().result == "failed"
    assert "missing" in platform.bodies[next(p for p in platform.bodies if p.endswith("/failure"))]["error"]


def test_a_storage_that_is_down_gives_the_version_back_and_the_job_is_tried_again(
    platform: FakePlatform, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform.to_read = [platform.add_file("train.csv", CSV)]
    platform.storage_failure = 503
    monkeypatch.setattr(tasks.process_version, "retry", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("retry")))
    result = run()
    assert not result.successful()
    assert any(path.endswith("/release") for _, path in platform.calls)
    assert not any(path.endswith("/failure") or path.endswith("/result") for _, path in platform.calls)


def test_the_key_goes_to_the_api_and_never_to_the_storage(platform: FakePlatform) -> None:
    platform.to_read = [platform.add_file("train.csv", CSV)]
    run()
    storage_requests = len(platform.keys) - len(platform.calls)
    assert storage_requests == 1
    assert platform.keys.count(KEY) == len(platform.calls)  # every call to the API carries it, nothing else


def test_the_sweep_queues_the_versions_that_wait(platform: FakePlatform, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    platform.waiting_ids = ids
    queued: list[list[str]] = []
    monkeypatch.setattr(tasks.process_version, "apply_async", lambda args: queued.append(args))
    assert tasks.process_waiting.apply().result == 2
    assert queued == [[i] for i in ids]


def test_the_sweep_queues_the_versions_of_models_too(platform: FakePlatform, monkeypatch: pytest.MonkeyPatch) -> None:
    platform.waiting_model_ids = [str(uuid.uuid4())]
    queued: list[list[str]] = []
    monkeypatch.setattr(tasks.process_model_version, "apply_async", lambda args: queued.append(args))
    assert tasks.process_waiting.apply().result == 1
    assert queued == [platform.waiting_model_ids]


def test_the_job_that_expires_the_uploads_says_how_many(platform: FakePlatform) -> None:
    assert tasks.expire_uploads.apply().result == 2


def test_the_schedule_names_tasks_that_exist() -> None:
    names = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert names <= set(celery_app.tasks)
    assert "datasets.process_version" in celery_app.tasks  # the name the API queues it by


def test_an_api_that_refuses_is_an_error_of_the_job(platform: FakePlatform, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "handle", lambda request: httpx2.Response(401))
    monkeypatch.setattr(
        tasks,
        "_backend",
        lambda: tasks.Backend("http://api.test", "x", transport=httpx2.MockTransport(platform.handle)),
    )
    assert not run().successful()


# ---- the fingerprints of the files of a model


def check(version: uuid.UUID | None = None):
    return tasks.process_model_version.apply(args=[str(version or uuid.uuid4())])


def test_the_files_of_a_model_are_fingerprinted_and_the_api_is_told(platform: FakePlatform) -> None:
    weights = b"\x00weights" * 1000
    platform.to_read = [platform.add_file("weights.bin", weights, rows=False), platform.add_file("c.json", b"{}")]
    result = check()
    assert result.successful() and result.result == "ready"
    files = platform.bodies[
        next(p for p in platform.bodies if p.startswith("/model-versions/") and p.endswith("/result"))
    ]
    assert [(f["size_bytes"], f["sha256"]) for f in files["files"]] == [
        (len(weights), sha256(weights)),
        (2, sha256(b"{}")),
    ]
    assert all("rows" not in f for f in files["files"])  # nothing is read in a model file


def test_nothing_to_check_when_the_version_is_not_up_for_the_taking(platform: FakePlatform) -> None:
    platform.to_read = None
    assert check().result is None


def test_a_model_file_missing_from_the_storage_fails_the_version(platform: FakePlatform) -> None:
    gone = platform.add_file("weights.bin", b"x", rows=False)
    del platform.files[gone["url"]]
    platform.to_read = [gone]
    assert check().result == "failed"
    body = platform.bodies[next(p for p in platform.bodies if p.endswith("/failure"))]
    assert "weights.bin" in body["error"]


def test_a_storage_that_is_down_gives_the_model_version_back(
    platform: FakePlatform, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform.to_read = [platform.add_file("weights.bin", b"x", rows=False)]
    platform.storage_failure = 503
    monkeypatch.setattr(
        tasks.process_model_version, "retry", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("retry"))
    )
    assert not check().successful()
    assert any(path.endswith("/release") for _, path in platform.calls)
    assert not any(path.endswith("/failure") or path.endswith("/result") for _, path in platform.calls)


def test_a_big_file_is_not_kept_while_it_is_fingerprinted(
    platform: FakePlatform, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    created: list[object] = []
    real = tempfile.TemporaryFile
    monkeypatch.setattr(tempfile, "TemporaryFile", lambda *a, **k: created.append(1) or real(*a, **k))
    platform.to_read = [platform.add_file("weights.bin", b"x" * 100, rows=False)]
    check()
    assert created == []  # no copy on the disk: only the digest is kept


def test_the_task_has_the_name_the_api_queues_it_by() -> None:
    assert "models.process_version" in celery_app.tasks
