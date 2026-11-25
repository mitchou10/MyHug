"""The routes of the worker that computes the metrics of an evaluation. The test plays the worker: it takes the
evaluation in hand, reads what it is given, and says what it found."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ModelEvaluation
from tests.routers import test_dataset_files
from tests.routers.test_model_evaluations import DATASET, URL, begin, body, queue, send, start  # noqa: F401
from tests.routers.test_models import MODELS, create

KEY = "worker-key-of-sixteen-characters"
HEADERS = {"X-Api-Key": KEY}
BASE = "/api/internal/model-evaluations"
work = test_dataset_files.work


@pytest.fixture(autouse=True)
def worker_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WORKER_API_KEY", KEY)


async def pending(client, login, db, work, store) -> dict:
    """An evaluation whose predictions all arrived: it waits for a worker."""
    await start(client, login, db, work)
    evaluation = await begin(client)
    done = await send(client, store, evaluation)
    assert done["status"] == "pending"
    return evaluation


async def claim(client: httpx2.AsyncClient, evaluation_id: str) -> dict:
    response = await client.post(f"{BASE}/{evaluation_id}/claim", headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


async def status_of(db: AsyncSession, evaluation_id: str) -> ModelEvaluation:
    db.expire_all()
    return (await db.execute(select(ModelEvaluation).where(ModelEvaluation.id == evaluation_id))).scalar_one()


# ---- what a worker is given


async def test_the_worker_is_given_what_it_needs_and_the_evaluation_is_its_own(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    taken = await claim(client, evaluation["id"])
    assert taken["claimed"] is True and taken["id"] == evaluation["id"]
    assert (taken["task"], taken["split"], taken["target_column"]) == ("classification", "test", "label")
    assert (taken["prediction_column"], taken["key_column"], taken["predictions_format"]) == (
        "prediction",
        None,
        "jsonl",
    )
    assert taken["metrics"] == ["accuracy", "precision", "recall", "f1"]  # the AUC needs scores: it is not computed
    assert [f["path"] for f in taken["truth"]] == ["test.csv"] and taken["truth"][0]["url"].startswith("memory://get/")
    assert taken["predictions"]["size_bytes"] == len(test_predictions()) and taken["predictions"]["url"].startswith(
        "memory://"
    )
    stored = await status_of(db, evaluation["id"])
    assert (stored.status, stored.attempts) == ("running", 1) and stored.processing_started_at is not None


def test_predictions() -> bytes:
    from tests.routers.test_model_evaluations import PREDICTIONS

    return PREDICTIONS


async def test_the_files_of_the_split_come_in_the_order_of_the_items(client, login, db, work, store) -> None:
    await start(client, login, db, work)
    from tests.routers.test_dataset_files import ADDRESS, part, push

    await push(
        client,
        part("test-2.csv", b"text,label\nmore,pos\n"),
        part("test-1.csv", b"text,label\nfirst,neg\n"),
        address=ADDRESS,
    )
    await work()
    evaluation = await begin(client, dataset_version=2)
    await send(client, store, evaluation)
    taken = await claim(client, evaluation["id"])
    assert [f["path"] for f in taken["truth"]] == [
        "test-1.csv",
        "test-2.csv",
        "test.csv",
    ]  # by path, as the preview reads


async def test_a_second_worker_gets_nothing(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    assert (await claim(client, evaluation["id"]))["claimed"] is True
    assert (await claim(client, evaluation["id"]))["claimed"] is False
    assert (await status_of(db, evaluation["id"])).attempts == 1  # the second call was not an attempt


async def test_an_evaluation_that_is_not_up_for_the_taking_is_not_given(client, login, db, work, store) -> None:
    await start(client, login, db, work)
    uploading = await begin(client)  # its predictions did not arrive
    assert (await claim(client, uploading["id"]))["claimed"] is False
    assert (await claim(client, str(uuid.uuid4())))["claimed"] is False
    assert (await status_of(db, uploading["id"])).status == "uploading"


async def test_a_worker_that_died_loses_the_evaluation_after_a_while(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    await db.execute(
        update(ModelEvaluation)
        .where(ModelEvaluation.id == evaluation["id"])
        .values(processing_started_at=datetime.now(UTC) - timedelta(minutes=settings.PROCESSING_STALE_MINUTES + 1))
    )
    await db.commit()
    assert (await claim(client, evaluation["id"]))["claimed"] is True
    assert (await status_of(db, evaluation["id"])).attempts == 2


async def test_it_is_given_up_after_too_many_attempts(client, login, db, work, store, monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROCESSING_MAX_ATTEMPTS", 1)
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    await client.post(f"{BASE}/{evaluation['id']}/release", headers=HEADERS)
    assert (await claim(client, evaluation["id"]))["claimed"] is False
    stored = await status_of(db, evaluation["id"])
    assert stored.status == "failed" and "interrupted too many times" in (stored.error or "")


async def test_a_dataset_that_was_deleted_fails_the_evaluation_with_the_reason(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    assert (await client.delete(f"/api/datasets/{DATASET}")).status_code == 204
    assert (await claim(client, evaluation["id"]))["claimed"] is False
    stored = await status_of(db, evaluation["id"])
    assert stored.status == "failed" and "dataset of this evaluation was deleted" in (stored.error or "")


# ---- what the worker says


async def test_the_metrics_are_kept_and_the_evaluation_is_done(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    done = await client.post(
        f"{BASE}/{evaluation['id']}/result",
        json={"results": {"f1": 0.5, "accuracy": 0.75, "precision": 0.6}, "items": 2},
        headers=HEADERS,
    )
    assert done.status_code == 200 and done.json() == {"status": "done"}
    seen = (await client.get(f"{URL}/{evaluation['id']}")).json()
    assert seen["status"] == "done" and seen["source"] == "predictions" and seen["items"] == 2
    assert seen["results"] == {"f1": 0.5, "accuracy": 0.75, "precision": 0.6}
    assert seen["shown"] == ["accuracy", "precision"]  # the main one and the next that were computed
    assert seen["finished_at"] is not None and seen["error"] is None
    login("u2", "bob")
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["results"] == {"accuracy": 0.75, "precision": 0.6}


@pytest.mark.parametrize(
    "results",
    [{}, {"wer": 0.1}, {"accuracy": True}, {"accuracy": "high"}, {"auc_roc": 0.9}, {"Accuracy": 0.5}],
)
async def test_what_cannot_be_a_result_is_refused(client, login, db, work, store, results) -> None:
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    answer = await client.post(
        f"{BASE}/{evaluation['id']}/result", json={"results": results, "items": 1}, headers=HEADERS
    )
    assert answer.status_code == 422, answer.text
    assert (await status_of(db, evaluation["id"])).status == "running"  # nothing was written


@pytest.mark.parametrize("value", ["NaN", "Infinity"])
async def test_nan_and_infinity_are_not_metrics_even_from_the_worker(client, login, db, work, store, value) -> None:
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    raw = f'{{"results": {{"accuracy": {value}}}, "items": 1}}'
    answer = await client.post(
        f"{BASE}/{evaluation['id']}/result", content=raw, headers={**HEADERS, "content-type": "application/json"}
    )
    assert answer.status_code == 422


async def test_a_result_is_only_taken_from_the_worker_that_has_the_evaluation(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    payload = {"results": {"accuracy": 1.0}, "items": 1}
    assert (await client.post(f"{BASE}/{evaluation['id']}/result", json=payload, headers=HEADERS)).status_code == 409
    await claim(client, evaluation["id"])
    assert (await client.post(f"{BASE}/{evaluation['id']}/result", json=payload, headers=HEADERS)).status_code == 200
    assert (await client.post(f"{BASE}/{evaluation['id']}/result", json=payload, headers=HEADERS)).status_code == 409
    assert (await client.post(f"{BASE}/{uuid.uuid4()}/result", json=payload, headers=HEADERS)).status_code == 404


async def test_a_failure_says_why_and_everybody_who_reads_the_evaluation_sees_it(
    client, login, db, work, store
) -> None:
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    failed = await client.post(
        f"{BASE}/{evaluation['id']}/failure", json={"error": "Row 3 of test has no prediction"}, headers=HEADERS
    )
    assert failed.json() == {"status": "failed"}
    login("u2", "bob")
    seen = (await client.get(f"{URL}/{evaluation['id']}")).json()
    assert seen["status"] == "failed" and seen["error"] == "Row 3 of test has no prediction" and seen["results"] == {}


async def test_the_reason_is_not_longer_than_the_limit(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    assert (
        await client.post(f"{BASE}/{evaluation['id']}/failure", json={"error": "x" * 2001}, headers=HEADERS)
    ).status_code == 422


async def test_an_evaluation_that_is_released_waits_again_and_is_taken_again(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    assert (await client.post(f"{BASE}/{evaluation['id']}/release", headers=HEADERS)).json() == {"status": "pending"}
    assert (await status_of(db, evaluation["id"])).status == "pending"
    assert (await claim(client, evaluation["id"]))["claimed"] is True
    assert (await status_of(db, evaluation["id"])).attempts == 2


async def test_releasing_does_not_undo_a_finished_evaluation(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    await claim(client, evaluation["id"])
    await client.post(
        f"{BASE}/{evaluation['id']}/result", json={"results": {"accuracy": 1.0}, "items": 1}, headers=HEADERS
    )
    await client.post(f"{BASE}/{evaluation['id']}/release", headers=HEADERS)
    assert (await status_of(db, evaluation["id"])).status == "done"


# ---- the sweep


async def test_the_evaluations_nobody_is_computing_are_listed_for_the_sweep(client, login, db, work, store) -> None:
    fresh = await pending(client, login, db, work, store)
    assert (await client.get(f"{BASE}/waiting", headers=HEADERS)).json() == {"ids": []}  # the job is about to start
    old = datetime.now(UTC) - timedelta(minutes=10)
    await db.execute(update(ModelEvaluation).where(ModelEvaluation.id == fresh["id"]).values(created_at=old))
    await db.commit()
    assert (await client.get(f"{BASE}/waiting", headers=HEADERS)).json() == {"ids": [fresh["id"]]}
    await claim(client, fresh["id"])
    assert (await client.get(f"{BASE}/waiting", headers=HEADERS)).json() == {"ids": []}  # somebody has it
    await db.execute(
        update(ModelEvaluation)
        .where(ModelEvaluation.id == fresh["id"])
        .values(processing_started_at=datetime.now(UTC) - timedelta(minutes=settings.PROCESSING_STALE_MINUTES + 1))
    )
    await db.commit()
    assert (await client.get(f"{BASE}/waiting", headers=HEADERS)).json() == {"ids": [fresh["id"]]}  # its worker died


async def test_an_evaluation_that_is_still_receiving_its_predictions_is_not_waiting(
    client, login, db, work, store
) -> None:
    await start(client, login, db, work)
    uploading = await begin(client)
    await db.execute(
        update(ModelEvaluation)
        .where(ModelEvaluation.id == uploading["id"])
        .values(created_at=datetime.now(UTC) - timedelta(days=1))
    )
    await db.commit()
    assert (await client.get(f"{BASE}/waiting", headers=HEADERS)).json() == {"ids": []}


# ---- who may call


async def test_only_the_worker_calls_these_routes(client, login, db, work, store) -> None:
    evaluation = await pending(client, login, db, work, store)
    for method, path in (
        ("POST", f"{BASE}/{evaluation['id']}/claim"),
        ("POST", f"{BASE}/{evaluation['id']}/result"),
        ("POST", f"{BASE}/{evaluation['id']}/failure"),
        ("POST", f"{BASE}/{evaluation['id']}/release"),
        ("GET", f"{BASE}/waiting"),
    ):
        for headers in ({}, {"X-Api-Key": "x" * 32}):
            assert (await client.request(method, path, headers=headers, json={})).status_code == 401, (method, path)


# ---- what the platform computes


async def test_a_task_the_platform_does_not_compute_yet_is_refused_when_it_starts(client, login, db, work) -> None:
    await start(client, login, db, work)
    await create(client, "tagger", tasks=["ner"])
    from tests.routers.test_models import register

    await register(db, "ada/tagger")
    answer = await client.post(f"{MODELS}/ada/tagger/evaluations", json=body(task="ner"))
    assert answer.status_code == 422 and "does not compute the metrics of ner yet" in answer.json()["detail"]
