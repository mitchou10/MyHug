import json

import httpx2
import pytest

from myhug import errors
from tests.fake import FakePlatform
from tests.helpers import get, run

RESULT = {"accuracy": 0.91, "f1": 0.8}
WHERE = {"dataset": "ada/reviews", "split": "test", "target_column": "label"}


async def open_model(driver, platform: FakePlatform, *, versions: int = 2, tasks: list[str] | None = None):
    entity = platform.catalog.add("models", "ada/sentiment", {"w.bin": b"1234"})
    for _ in range(versions - 1):
        platform.catalog.new_version(entity, {"w.bin": b"1234"})
    return await get(driver, "models", "ada/sentiment")


# ---- the metrics


async def test_the_metrics_of_every_task_are_read_from_the_platform(driver, platform) -> None:
    listed = await run(driver, driver.client.metrics.list)
    assert [t.task for t in listed] == ["classification", "regression"]
    classification = listed[0]
    assert [m.id for m in classification.metrics] == ["accuracy", "precision", "recall", "f1", "auc"]
    assert classification.metrics[0].primary and classification.default_shown == ["accuracy", "precision"]
    mae = next(m for m in listed[1].metrics if m.id == "mae")
    assert mae.higher is False  # an error: lower is better


async def test_one_task_and_the_ids_of_its_metrics(driver, platform) -> None:
    assert (await run(driver, driver.client.metrics.get, "regression")).task == "regression"
    assert await run(driver, driver.client.metrics.ids, "regression") == ["mae", "rmse", "r2", "mape"]
    with pytest.raises(ValueError, match="No task 'nothing': the tasks are classification, regression"):
        await run(driver, driver.client.metrics.get, "nothing")


# ---- evaluating from predictions


def jsonl(values: list) -> bytes:
    return b"".join(json.dumps({"prediction": v}).encode() + b"\n" for v in values)


def stored(platform: FakePlatform, evaluation_id: str) -> bytes | None:
    return platform.catalog.evaluations[str(evaluation_id)]["data"]


async def test_the_predictions_are_sent_in_parts_and_a_worker_is_waited_for(driver, platform) -> None:
    model = await open_model(driver, platform)
    values = ["pos", "neg", "pos", "pos", "neg", "neg", "pos", "neg"]
    evaluation = await run(
        driver,
        model.evaluate,
        "classification",
        values,
        note="my notebook",
        key_column="id",
        input_column="text",
        **WHERE,
    )
    assert platform.catalog.started == [
        {
            "version": 2, "task": "classification", "dataset": "ada/reviews", "split": "test", "target_column": "label",
            "key_column": "id", "input_column": "text", "prediction_column": "prediction", "format": "jsonl",
            "size": len(jsonl(values)), "note": "my notebook",
        }
    ]  # fmt: skip
    assert evaluation.status == "pending" and evaluation.source.value == "predictions" and evaluation.results == {}
    assert stored(platform, evaluation.id) == jsonl(values)  # the parts were put together as they were sent
    assert len([c for c in platform.storage_calls if c[0] == "PUT"]) == -(-len(jsonl(values)) // 4)


async def test_nothing_of_the_token_goes_to_the_storage(driver, platform) -> None:
    model = await open_model(driver, platform)
    await run(driver, model.evaluate, "classification", ["a", "b"], **WHERE)
    puts = [r for r in platform.requests if r.url.host == "storage.test" and r.method == "PUT"]
    assert puts and all("authorization" not in r.headers for r in puts)


async def test_a_file_is_sent_as_it_is_with_its_format_from_its_name(driver, platform, tmp_path) -> None:
    model = await open_model(driver, platform)
    for name, fmt in (("p.csv", "csv"), ("p.jsonl", "jsonl"), ("p.ndjson", "jsonl"), ("p.parquet", "parquet")):
        file = tmp_path / name
        file.write_bytes(b"prediction\n1\n2\n")
        evaluation = await run(driver, model.evaluate, "classification", file, **WHERE)
        assert (
            platform.catalog.started[-1]["format"] == fmt
            and platform.catalog.started[-1]["size"] == file.stat().st_size
        )
        assert stored(platform, evaluation.id) == file.read_bytes()
    assert not list((tmp_path / "cache" / "predictions").glob("*"))  # nothing was left behind


async def test_a_list_of_objects_is_one_object_a_line(driver, platform) -> None:
    model = await open_model(driver, platform)
    rows = [{"id": 1, "prediction": "a"}, {"id": 2, "prediction": "b"}]
    evaluation = await run(driver, model.evaluate, "classification", rows, key_column="id", **WHERE)
    assert stored(platform, evaluation.id) == b'{"id": 1, "prediction": "a"}\n{"id": 2, "prediction": "b"}\n'


async def test_another_version_and_the_column_of_the_predictions_can_be_chosen(driver, platform) -> None:
    model = await open_model(driver, platform)
    await run(
        driver,
        model.evaluate,
        "classification",
        [1, 2],
        version=1,
        dataset_version=3,
        prediction_column="label",
        **WHERE,
    )
    sent = platform.catalog.started[0]
    assert (sent["version"], sent["dataset_version"], sent["prediction_column"]) == (1, 3, "label")


async def test_the_progress_goes_forward_to_the_size(driver, platform) -> None:
    model = await open_model(driver, platform)
    seen = []
    await run(driver, model.evaluate, "classification", ["x"] * 10, progress=seen.append, **WHERE)
    assert seen[0].done == 0 and seen[-1].done == seen[-1].total == len(jsonl(["x"] * 10))
    assert [p.done for p in seen] == sorted(p.done for p in seen)


@pytest.mark.parametrize(
    ("predictions", "message"),
    [
        ([], "no prediction"),
        ([float("nan")], "nan and infinity"),
        ([float("inf")], "nan and infinity"),
        ("nothing.jsonl", "is not a file"),
        ("p.xml", "a .jsonl, .csv or .parquet file"),
    ],
)
async def test_predictions_that_cannot_be_right_are_refused_before_anything_is_asked(
    driver, platform, tmp_path, predictions, message
) -> None:
    model = await open_model(driver, platform)
    if predictions == "p.xml":
        (tmp_path / "p.xml").write_text("<x/>")
        predictions = tmp_path / "p.xml"
    elif isinstance(predictions, str):
        predictions = tmp_path / predictions
    before = len(platform.requests)
    with pytest.raises(ValueError, match=message):
        await run(driver, model.evaluate, "classification", predictions, **WHERE)
    assert len(platform.requests) == before and not list((tmp_path / "cache" / "predictions").glob("*"))


async def test_what_the_platform_refuses_is_an_error_with_its_sentence_and_nothing_is_sent(driver, platform) -> None:
    model = await open_model(driver, platform)
    with pytest.raises(errors.Invalid, match="does not do ner"):
        await run(driver, model.evaluate, "ner", ["a"], **WHERE)
    with pytest.raises(errors.Invalid, match="No dataset ada/nothing"):
        await run(driver, model.evaluate, "classification", ["a"], **{**WHERE, "dataset": "ada/nothing"})
    assert not [c for c in platform.storage_calls if c[0] == "PUT"]


async def test_somebody_who_cannot_edit_the_model_gets_a_permission_error(driver, platform) -> None:
    model = await open_model(driver, platform)
    platform.say("POST", "/api/models/ada/sentiment/evaluations", httpx2.Response(403, json={"detail": "Not allowed"}))
    with pytest.raises(errors.PermissionDenied):
        await run(driver, model.evaluate, "classification", ["a"], **WHERE)


async def test_an_evaluation_is_never_started_twice_by_itself(driver, platform) -> None:
    model = await open_model(driver, platform)
    platform.say("POST", "/api/models/ada/sentiment/evaluations", httpx2.Response(503, json={"detail": "busy"}))
    with pytest.raises(errors.ServerError):
        await run(driver, model.evaluate, "classification", ["a"], **WHERE)
    assert len(platform.api_calls("POST", "/api/models/ada/sentiment/evaluations")) == 1


async def test_a_model_with_no_version_cannot_be_evaluated(driver, platform) -> None:
    platform.catalog.add("models", "ada/sentiment")
    model = await get(driver, "models", "ada/sentiment")
    with pytest.raises(ValueError, match="no version"):
        await run(driver, model.evaluate, "classification", ["a"], **WHERE)


# ---- how the predictions were made


async def test_the_time_and_the_hardware_are_sent_and_come_back_as_declared(driver, platform) -> None:
    model = await open_model(driver, platform)
    hardware = {"device": "cpu", "cpu": "AMD EPYC", "cpu_cores": 8, "ram_gb": 32.0, "runtime": "onnxruntime 1.20"}
    evaluation = await run(
        driver, model.evaluate, "classification", ["a"], inference_seconds=12.5, hardware=hardware, **WHERE
    )
    assert platform.catalog.started[0]["inference"] == {"seconds": 12.5, "hardware": hardware}
    assert evaluation.inference.seconds == 12.5 and evaluation.inference.origin.value == "declared"
    assert evaluation.inference.hardware.cpu_cores == 8 and evaluation.inference.ms_per_item is None


async def test_nothing_about_the_machine_is_sent_unless_it_is_asked(driver, platform) -> None:
    model = await open_model(driver, platform)
    await run(driver, model.evaluate, "classification", ["a"], **WHERE)
    assert "inference" not in platform.catalog.started[0]
    await run(driver, model.evaluate, "classification", ["a"], inference_seconds=2, **WHERE)
    assert platform.catalog.started[1]["inference"] == {"seconds": 2.0}  # only the time, no hardware


async def test_this_machine_is_read_when_asked(driver, platform, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("myhug.models.detect", lambda: {"device": "cpu", "cpu": "Test CPU", "cpu_cores": 4})
    model = await open_model(driver, platform)
    await run(driver, model.evaluate, "classification", ["a"], hardware=True, **WHERE)
    assert platform.catalog.started[0]["inference"] == {
        "hardware": {"device": "cpu", "cpu": "Test CPU", "cpu_cores": 4}
    }


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf"), "slow", True])
async def test_a_time_that_cannot_be_right_is_refused_before_anything_is_asked(driver, platform, seconds) -> None:
    model = await open_model(driver, platform)
    before = len(platform.requests)
    with pytest.raises(ValueError, match="number of seconds"):
        await run(driver, model.evaluate, "classification", ["a"], inference_seconds=seconds, **WHERE)
    assert len(platform.requests) == before


# ---- an interruption, and going on


async def test_an_interrupted_sending_says_which_evaluation_to_go_on_with(driver, platform) -> None:
    model = await open_model(driver, platform)
    platform.refuse_parts = 1000
    with pytest.raises(errors.UploadError) as raised:
        await run(driver, model.evaluate, "classification", ["x"] * 6, **WHERE)
    identifier = next(iter(platform.catalog.evaluations))
    assert identifier in str(raised.value) and "send_predictions" in str(raised.value)
    assert platform.catalog.evaluations[identifier]["view"]["status"] == "uploading"


async def test_it_goes_on_with_the_parts_that_are_not_there(driver, platform) -> None:
    model = await open_model(driver, platform)
    values = ["x"] * 6  # a few parts
    platform.refuse_parts = 1000
    with pytest.raises(errors.UploadError):
        await run(driver, model.evaluate, "classification", values, **WHERE)
    identifier = next(iter(platform.catalog.evaluations))
    # Two parts did arrive before the storage went down.
    for n in (1, 2):
        platform.parts[(f"evaluation-{identifier}", "file", n)] = jsonl(values)[(n - 1) * 4 : n * 4]
    platform.refuse_parts = 0
    before = len([c for c in platform.storage_calls if c[0] == "PUT"])
    seen = []
    done = await run(driver, model.send_predictions, identifier, values, progress=seen.append)
    sent_now = len([c for c in platform.storage_calls if c[0] == "PUT"]) - before
    assert done.status == "pending" and stored(platform, identifier) == jsonl(values)
    assert sent_now == -(-len(jsonl(values)) // 4) - 2  # not the two that were there
    assert seen[0].done == 8  # and the progress starts from what is there


async def test_a_file_that_is_not_the_one_announced_is_not_sent(driver, platform) -> None:
    model = await open_model(driver, platform)
    platform.refuse_parts = 1000
    with pytest.raises(errors.UploadError):
        await run(driver, model.evaluate, "classification", ["x"] * 6, **WHERE)
    identifier = next(iter(platform.catalog.evaluations))
    platform.refuse_parts = 0
    with pytest.raises(errors.FileChanged):
        await run(driver, model.send_predictions, identifier, ["y"] * 3)
    assert not [
        c for c in platform.storage_calls if c[0] == "PUT" and "evaluation" in c[1] and c[1].endswith("/1") and False
    ]


# ---- waiting for the worker


async def test_it_waits_for_the_worker_and_gives_back_the_metrics(build, platform) -> None:
    for mode in ("sync", "async"):
        d = build(mode)
        model = await open_model(d, platform)
        marker: list[str] = []

        def settle(seconds: float, marker=marker) -> None:
            ident = next(reversed(platform.catalog.evaluations))
            marker.append(ident)
            platform.catalog.finish(ident, RESULT)

        async def asettle(seconds: float) -> None:
            settle(seconds)

        d.client._sleep = settle if mode == "sync" else asettle  # type: ignore[assignment]
        evaluation = await run(d, model.evaluate, "classification", ["a", "b"], wait=True, **WHERE)
        assert evaluation.status == "done" and evaluation.results == RESULT and evaluation.source.value == "predictions"
        platform.catalog.evaluations.clear()


async def test_a_failure_of_the_worker_is_an_error_with_its_reason(build, platform) -> None:
    d = build("sync")
    model = await open_model(d, platform)

    def settle(seconds: float) -> None:
        platform.catalog.finish(
            next(reversed(platform.catalog.evaluations)), {}, error="Row 3 of test has no prediction"
        )

    d.client._sleep = settle  # type: ignore[assignment]
    with pytest.raises(errors.EvaluationFailed, match="Row 3 of test has no prediction") as raised:
        await run(d, model.evaluate, "classification", ["a"], wait=True, **WHERE)
    assert raised.value.reason == "Row 3 of test has no prediction"


async def test_it_gives_up_waiting_after_its_timeout(driver, platform, sleeps) -> None:
    model = await open_model(driver, platform)
    with pytest.raises(errors.WaitTimeout, match="still pending"):
        await run(driver, model.evaluate, "classification", ["a"], wait=True, timeout=4, **WHERE)
    assert sleeps == [2.0, 2.0]


async def test_a_started_evaluation_can_be_waited_for_later(driver, platform) -> None:
    model = await open_model(driver, platform)
    sent = await run(driver, model.evaluate, "classification", ["a"], **WHERE)
    platform.catalog.finish(str(sent.id), RESULT)
    assert (await run(driver, model.wait_evaluation, sent.id)).results == RESULT


# ---- reading, choosing, deleting


async def finished(driver, platform, model, results: dict[str, float] = RESULT, **options):
    evaluation = await run(driver, model.evaluate, "classification", ["a"], **{**WHERE, **options})
    platform.catalog.finish(str(evaluation.id), results)
    return evaluation


async def test_the_evaluations_come_newest_first_and_can_be_filtered(driver, platform) -> None:
    model = await open_model(driver, platform)
    first = await finished(driver, platform, model, version=1)
    second = await finished(driver, platform, model)
    assert [e.id for e in await run(driver, model.evaluations)] == [second.id, first.id]
    assert [e.id for e in await run(driver, model.evaluations, version=1)] == [first.id]
    assert (await run(driver, model.evaluation, first.id)).results == RESULT


async def test_a_long_list_is_read_page_after_page(driver, platform) -> None:
    model = await open_model(driver, platform)
    for _ in range(120):
        await run(driver, model.evaluate, "classification", ["a"], **WHERE)
    found = await run(driver, model.evaluations)
    assert len(found) == 120 and len({e.id for e in found}) == 120
    pages = platform.api_calls("GET", "/api/models/ada/sentiment/evaluations")
    assert [r.url.params["offset"] for r in pages] == ["0", "50", "100"]


async def test_the_metrics_the_others_see_are_chosen_and_an_evaluation_deleted(driver, platform) -> None:
    model = await open_model(driver, platform)
    sent = await finished(driver, platform, model)
    changed = await run(driver, model.set_shown, sent.id, ["f1"])
    assert changed.shown == ["f1"] and changed.results == RESULT  # all the metrics are kept
    await run(driver, model.delete_evaluation, sent.id)
    assert await run(driver, model.evaluations) == []
    with pytest.raises(errors.NotFound):
        await run(driver, model.evaluation, sent.id)
