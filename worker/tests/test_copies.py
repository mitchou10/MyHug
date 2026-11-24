import io
import uuid

import pyarrow.parquet as pq
import pytest

from tests.conftest import KEY, FakePlatform
from worker import copier, tasks
from worker.config import settings

CSV = b"n,t\n" + b"".join(f"{i},row {i}\n".encode() for i in range(100))


def run(derivative: uuid.UUID | None = None):
    return tasks.convert_file.apply(args=[str(derivative or uuid.uuid4())])


def offer(platform: FakePlatform, path: str = "train.csv", data: bytes = CSV, part_bytes: int = 5 * 1024**2) -> str:
    source = platform.add_file(path, data)
    platform.copy = {
        "id": str(uuid.uuid4()),
        "source_url": source["url"],
        "source_path": path,
        "source_size_bytes": len(data),
        "part_bytes": part_bytes,
    }
    return source["url"]


def test_a_copy_is_made_sent_in_parts_and_the_api_is_told(platform: FakePlatform) -> None:
    offer(platform)
    result = run()
    assert result.successful() and result.result == "ready"
    sent = b"".join(platform.uploaded[n] for n in sorted(platform.uploaded))
    assert pq.ParquetFile(io.BytesIO(sent)).metadata.num_rows == 100  # what reached the storage is the copy
    body = platform.bodies[next(p for p in platform.bodies if p.endswith("/result"))]
    assert body["rows"] == 100 and body["columns"] == [{"name": "n", "dtype": "int"}, {"name": "t", "dtype": "string"}]


def test_a_copy_that_is_larger_than_a_part_goes_in_several(platform: FakePlatform) -> None:
    offer(platform, part_bytes=300)
    run()
    assert len(platform.uploaded) > 1
    assert all(len(data) == 300 for number, data in platform.uploaded.items() if number < max(platform.uploaded))


def test_there_is_nothing_to_do_when_the_copy_is_not_up_for_the_taking(platform: FakePlatform) -> None:
    platform.copy = None
    assert run().result is None and not platform.uploaded


def test_a_source_that_cannot_be_read_fails_the_copy_with_the_reason(platform: FakePlatform) -> None:
    offer(platform, "bad.jsonl", b"not json\n")
    assert run().result == "failed"
    assert "bad.jsonl" in platform.bodies[next(p for p in platform.bodies if p.endswith("/failure"))]["error"]
    assert not platform.uploaded


def test_a_source_missing_from_the_storage_fails_the_copy(platform: FakePlatform) -> None:
    url = offer(platform)
    del platform.files[url]
    assert run().result == "failed"


def test_a_storage_that_is_down_gives_the_copy_back_and_the_job_is_tried_again(platform: FakePlatform) -> None:
    offer(platform)
    platform.storage_failure = 503
    assert not run().successful()
    assert any(path.endswith("/release") for _, path in platform.calls)
    assert not any(path.endswith("/failure") or path.endswith("/result") for _, path in platform.calls)


def test_the_key_never_goes_to_the_storage(platform: FakePlatform) -> None:
    offer(platform)
    run()
    api_calls = len(platform.calls)
    assert platform.keys.count(KEY) == api_calls and len(platform.keys) > api_calls


def test_the_sweep_queues_the_copies_that_wait_too(platform: FakePlatform, monkeypatch: pytest.MonkeyPatch) -> None:
    version, copy = str(uuid.uuid4()), str(uuid.uuid4())
    platform.waiting_ids, platform.waiting_copy_ids = [version], [copy]
    queued: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(tasks.process_version, "apply_async", lambda args: queued.append(("version", args)))
    monkeypatch.setattr(tasks.convert_file, "apply_async", lambda args: queued.append(("copy", args)))
    assert tasks.process_waiting.apply().result == 2
    assert queued == [("version", [version]), ("copy", [copy])]


def test_an_empty_copy_is_still_sent_as_one_part(platform: FakePlatform, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ROW_GROUP_ROWS", 10)
    offer(platform, data=b"n\n")
    run()
    assert list(platform.uploaded) == [1]


def test_the_number_of_parts_follows_the_size_of_the_copy() -> None:
    sent: list[list[int]] = []

    class Fake:
        def sign_copy_parts(self, _id, numbers):
            sent.append(numbers)
            return {n: f"u{n}" for n in numbers}

        def upload_part(self, url, data):
            pass

    target = io.BytesIO(b"x" * 250)
    copier._send(Fake(), uuid.uuid4(), target, 100)  # ty: ignore[invalid-argument-type]
    assert sent == [[1, 2, 3]]
