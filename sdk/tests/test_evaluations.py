import httpx2
import pytest

from myhug import errors
from tests.fake import FakePlatform
from tests.helpers import get, run

RESULT = {"accuracy": 0.91, "f1": 0.8}


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


# ---- sending a result


async def test_a_result_is_sent_for_the_latest_version_and_comes_back_as_sent(driver, platform) -> None:
    model = await open_model(driver, platform)
    evaluation = await run(
        driver, model.submit_evaluation, "classification", RESULT, dataset="ada/reviews", split="test", items=1200,
        target_column="label", note="5-fold cross-validation",
    )  # fmt: skip
    assert platform.catalog.submitted == [
        {
            "version": 2, "task": "classification", "results": RESULT, "note": "5-fold cross-validation",
            "dataset": "ada/reviews", "split": "test", "items": 1200, "target_column": "label",
        }
    ]  # fmt: skip
    assert evaluation.source == "submitted" and evaluation.status == "done" and evaluation.results == RESULT
    assert (evaluation.version, evaluation.items, evaluation.shown) == (2, 1200, ["accuracy", "precision"])


async def test_only_what_is_given_is_sent(driver, platform) -> None:
    model = await open_model(driver, platform)
    await run(driver, model.submit_evaluation, "classification", {"f1": 1})
    assert platform.catalog.submitted == [{"version": 2, "task": "classification", "results": {"f1": 1.0}, "note": ""}]


async def test_another_version_and_the_metrics_to_show_are_asked_for(driver, platform) -> None:
    model = await open_model(driver, platform)
    evaluation = await run(driver, model.submit_evaluation, "classification", RESULT, version=1, shown=["f1"])
    assert platform.catalog.submitted[0]["version"] == 1 and platform.catalog.submitted[0]["shown"] == ["f1"]
    assert evaluation.shown == ["f1"]


@pytest.mark.parametrize(
    ("results", "message"),
    [
        ({}, "at least one metric"),
        ({"accuracy": True}, "must be a finite number"),
        ({"accuracy": "high"}, "must be a finite number"),
        ({"accuracy": float("nan")}, "must be a finite number"),
        ({"accuracy": float("inf")}, "must be a finite number"),
        ({f"m{i}": 0.1 for i in range(51)}, "at most 50"),
    ],
)
async def test_a_result_that_cannot_be_right_is_refused_before_anything_is_sent(
    driver, platform, results, message
) -> None:
    model = await open_model(driver, platform)
    before = len(platform.requests)
    with pytest.raises(ValueError, match=message):
        await run(driver, model.submit_evaluation, "classification", results)
    assert len(platform.requests) == before


async def test_what_the_platform_refuses_is_an_error_with_its_sentence(driver, platform) -> None:
    model = await open_model(driver, platform)
    with pytest.raises(errors.Invalid, match="wer is not a metric of classification"):
        await run(driver, model.submit_evaluation, "classification", {"wer": 0.1})
    with pytest.raises(errors.Invalid, match="does not do ner"):
        await run(driver, model.submit_evaluation, "ner", {"f1": 0.1})


async def test_somebody_who_cannot_edit_the_model_gets_a_permission_error(driver, platform) -> None:
    model = await open_model(driver, platform)
    platform.say("POST", "/api/models/ada/sentiment/evaluations", httpx2.Response(403, json={"detail": "Not allowed"}))
    with pytest.raises(errors.PermissionDenied):
        await run(driver, model.submit_evaluation, "classification", RESULT)


async def test_a_result_is_never_sent_twice_by_itself(driver, platform) -> None:
    model = await open_model(driver, platform)
    platform.say("POST", "/api/models/ada/sentiment/evaluations", httpx2.Response(503, json={"detail": "busy"}))
    with pytest.raises(errors.ServerError):
        await run(driver, model.submit_evaluation, "classification", RESULT)
    assert len(platform.api_calls("POST", "/api/models/ada/sentiment/evaluations")) == 1  # it may have been kept


async def test_a_model_with_no_version_cannot_be_evaluated(driver, platform) -> None:
    platform.catalog.add("models", "ada/sentiment")
    model = await get(driver, "models", "ada/sentiment")
    with pytest.raises(ValueError, match="no version"):
        await run(driver, model.submit_evaluation, "classification", RESULT)


# ---- reading, choosing, deleting


async def test_the_evaluations_come_newest_first_and_can_be_filtered(driver, platform) -> None:
    model = await open_model(driver, platform)
    first = await run(driver, model.submit_evaluation, "classification", RESULT, version=1)
    second = await run(driver, model.submit_evaluation, "regression", {"mae": 1.5})
    assert [e.id for e in await run(driver, model.evaluations)] == [second.id, first.id]
    assert [e.id for e in await run(driver, model.evaluations, task="regression")] == [second.id]
    assert [e.id for e in await run(driver, model.evaluations, version=1)] == [first.id]
    assert (await run(driver, model.evaluation, first.id)).results == RESULT


async def test_a_long_list_is_read_page_after_page(driver, platform) -> None:
    model = await open_model(driver, platform)
    for i in range(120):
        await run(driver, model.submit_evaluation, "regression", {"mae": float(i)})
    found = await run(driver, model.evaluations)
    assert len(found) == 120 and len({e.id for e in found}) == 120
    pages = platform.api_calls("GET", "/api/models/ada/sentiment/evaluations")
    assert [r.url.params["offset"] for r in pages] == ["0", "50", "100"]


async def test_the_metrics_the_others_see_are_chosen_and_an_evaluation_deleted(driver, platform) -> None:
    model = await open_model(driver, platform)
    sent = await run(driver, model.submit_evaluation, "classification", RESULT)
    changed = await run(driver, model.set_shown, sent.id, ["f1"])
    assert changed.shown == ["f1"] and changed.results == RESULT  # all the metrics are kept
    await run(driver, model.delete_evaluation, sent.id)
    assert await run(driver, model.evaluations) == []
    with pytest.raises(errors.NotFound):
        await run(driver, model.evaluation, sent.id)
