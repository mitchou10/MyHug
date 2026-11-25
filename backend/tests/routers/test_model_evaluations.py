import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.config import settings
from app.main import app
from app.models import Dataset, ModelEvaluation
from app.routers.deps import get_jobs
from tests.conftest import MemoryStore
from tests.routers import test_dataset_files
from tests.routers.test_dataset_files import TEST, TRAIN, part, push
from tests.routers.test_datasets import create as create_dataset
from tests.routers.test_models import MODELS, create, register, share

URL = f"{MODELS}/ada/sentiment-fr/evaluations"
DATASET = "ada/movie-reviews"
PREDICTIONS = b'{"prediction": "pos"}\n{"prediction": "neg"}\n'

work = test_dataset_files.work  # the worker that reads the files of a dataset


class Queue:
    """What the API asked the worker to compute."""

    def __init__(self) -> None:
        self.evaluations: list[uuid.UUID] = []

    async def process_version(self, version_id: uuid.UUID) -> None: ...
    async def convert_file(self, derivative_id: uuid.UUID) -> None: ...
    async def process_model_version(self, version_id: uuid.UUID) -> None: ...
    async def resolve_code(self, version_id: uuid.UUID) -> None: ...

    async def evaluate(self, evaluation_id: uuid.UUID) -> None:
        self.evaluations.append(evaluation_id)


@pytest.fixture
def queue():
    jobs = Queue()
    app.dependency_overrides[get_jobs] = lambda: jobs
    yield jobs
    app.dependency_overrides.pop(get_jobs, None)


async def start(
    client: httpx2.AsyncClient, login, db: AsyncSession, work: Callable[[], Awaitable[None]], **model
) -> None:
    """A model of ada's with one version, and a dataset of hers with a train and a test split, read by the worker."""
    login("u1", "ada")
    await create(client, tasks=["classification", "regression"], **model)
    await register(db, "ada/sentiment-fr")
    await create_dataset(client)
    await push(client, part("train.csv", TRAIN), part("test.csv", TEST), address=f"/api/datasets/{DATASET}")
    await work()


def body(**changes) -> dict:
    return {
        "version": 1, "task": "classification", "dataset": DATASET, "split": "test", "target_column": "label",
        "format": "jsonl", "size": len(PREDICTIONS), **changes,
    }  # fmt: skip


async def begin(client: httpx2.AsyncClient, **changes) -> dict:
    response = await client.post(URL, json=body(**changes))
    assert response.status_code == 201, response.text
    return response.json()


async def send(client: httpx2.AsyncClient, store: MemoryStore, evaluation: dict, data: bytes = PREDICTIONS) -> dict:
    """What a program does: asks where each part goes, sends it there, and says it is complete."""
    state = (await client.get(f"{URL}/{evaluation['id']}/upload")).json()
    numbers = list(range(1, state["parts_count"] + 1))
    signed = (await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": numbers})).json()["parts"]
    for item in signed:
        start_at = (item["number"] - 1) * state["part_size"]
        store.receive(item["url"], data[start_at : start_at + state["part_size"]])
    done = await client.post(f"{URL}/{evaluation['id']}/upload/complete")
    assert done.status_code == 200, done.text
    return done.json()


# ---- the metrics


async def test_the_metrics_of_every_task_are_listed_for_a_person_who_is_logged_in(client, login) -> None:
    assert (await client.get("/api/metrics")).status_code == 401
    login("u1", "ada")
    listed = {t["task"]: t for t in (await client.get("/api/metrics")).json()}
    assert [m["id"] for m in listed["classification"]["metrics"]] == ["accuracy", "precision", "recall", "f1", "auc"]
    assert listed["classification"]["default_shown"] == ["accuracy", "precision"]
    mae = next(m for m in listed["regression"]["metrics"] if m["id"] == "mae")
    assert (mae["higher"], mae["primary"]) == (False, True)


# ---- starting an evaluation


async def test_an_evaluation_is_started_and_waits_for_its_predictions(client, login, db, work, store) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client, note="my notebook", key_column="text", input_column="text")
    assert (evaluation["source"], evaluation["status"], evaluation["version"], evaluation["task"]) == (
        "predictions", "uploading", 1, "classification",
    )  # fmt: skip
    assert (evaluation["dataset"], evaluation["dataset_version"], evaluation["split"]) == (DATASET, 1, "test")
    assert (evaluation["target_column"], evaluation["key_column"], evaluation["prediction_column"]) == (
        "label",
        "text",
        "prediction",
    )
    assert evaluation["results"] == {} and evaluation["shown"] == [] and evaluation["can_edit"] is True
    assert evaluation["predictions_format"] == "jsonl" and evaluation["predictions_size"] == len(PREDICTIONS)
    assert evaluation["note"] == "my notebook" and evaluation["created_by_username"] == "ada"
    state = (await client.get(f"{URL}/{evaluation['id']}/upload")).json()
    assert state["status"] == "uploading" and state["parts_count"] == 1 and state["received"] is None
    assert state["size_bytes"] == len(PREDICTIONS)


async def test_the_predictions_go_in_parts_and_a_worker_is_asked_to_compute(
    client, login, db, work, store, queue
) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    done = await send(client, store, evaluation)
    assert done["status"] == "pending" and done["source"] == "predictions" and done["results"] == {}
    assert queue.evaluations == [uuid.UUID(evaluation["id"])]
    stored = (await db.execute(select(ModelEvaluation))).scalar_one()
    assert stored.multipart_id is None and stored.expires_at is None
    assert store.objects[stored.predictions_key].data == PREDICTIONS
    assert stored.predictions_key == f"evaluations/{evaluation['id']}/predictions.jsonl"


async def test_a_large_file_has_several_parts_and_the_ones_that_arrived_can_be_asked(
    client, login, db, work, store, monkeypatch
) -> None:
    await start(client, login, db, work)
    monkeypatch.setattr("app.services.model_evaluations.part_size_for", lambda size, preferred: 10)
    data = bytes(range(35))
    evaluation = await begin(client, size=len(data))
    state = (await client.get(f"{URL}/{evaluation['id']}/upload")).json()
    assert (state["part_size"], state["parts_count"]) == (10, 4)
    signed = (await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": [1, 3]})).json()
    assert signed["expires_in"] == settings.SIGNED_ADDRESS_SECONDS
    for item in signed["parts"]:
        store.receive(item["url"], data[(item["number"] - 1) * 10 : item["number"] * 10])
    seen = (await client.get(f"{URL}/{evaluation['id']}/upload", params={"parts": True})).json()
    assert seen["received"] == [{"number": 1, "size": 10}, {"number": 3, "size": 10}]  # what is there to go on from
    missing = await client.post(f"{URL}/{evaluation['id']}/upload/complete")
    assert missing.status_code == 422 and "Part 2" in missing.json()["detail"]
    for n in (2, 4):
        url = (await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": [n]})).json()["parts"][0][
            "url"
        ]
        store.receive(url, data[(n - 1) * 10 : n * 10])
    assert (await client.post(f"{URL}/{evaluation['id']}/upload/complete")).json()["status"] == "pending"


async def test_a_part_of_the_wrong_size_is_refused_and_the_upload_stays_open(client, login, db, work, store) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    url = (await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": [1]})).json()["parts"][0]["url"]
    store.receive(url, PREDICTIONS[:-3])
    refused = await client.post(f"{URL}/{evaluation['id']}/upload/complete")
    assert refused.status_code == 422 and "bytes" in refused.json()["detail"]
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["status"] == "uploading"
    store.receive(url, PREDICTIONS)  # sent again
    assert (await client.post(f"{URL}/{evaluation['id']}/upload/complete")).status_code == 200


async def test_completing_again_changes_nothing_and_queues_nothing_more(client, login, db, work, store, queue) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    await send(client, store, evaluation)
    again = await client.post(f"{URL}/{evaluation['id']}/upload/complete")
    assert again.status_code == 200 and again.json()["status"] == "pending"
    assert len(queue.evaluations) == 1
    closed = await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": [1]})
    assert closed.status_code == 409  # nothing more is sent to a finished upload


async def test_numbers_of_parts_that_do_not_exist_are_refused(client, login, db, work) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    for numbers in ([0], [2], [1, 99]):
        response = await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": numbers})
        assert response.status_code == 422, numbers
    assert (await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": []})).status_code == 422


# ---- what is refused when it starts


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"task": "ner"}, "This model does not do ner"),
        ({"dataset": "ada/nothing"}, "No dataset ada/nothing"),
        ({"dataset_version": 7}, "No version 7"),
        ({"split": "validation"}, "has no split validation: it has train, test"),
        ({"target_column": "nothing"}, "has no column nothing"),
        ({"key_column": "nothing"}, "has no column nothing"),
        ({"size": settings.EVALUATION_PREDICTIONS_MAX_BYTES + 1}, "MiB"),
        ({"dataset": "not an address"}, ""),
        ({"format": "xml"}, ""),
        ({"size": 0}, ""),
        ({"version": 0}, ""),
        ({"split": ""}, "has no split"),
        ({"note": "x" * 1001}, ""),
    ],
)
async def test_what_cannot_be_right_is_refused_before_anything_is_stored(
    client, login, db, work, store, changes, message
) -> None:
    await start(client, login, db, work)
    response = await client.post(URL, json=body(**changes))
    assert response.status_code == 422, response.text
    if message:
        assert message in response.json()["detail"]
    assert (await client.get(URL)).json() == [] and store.uploads == {}  # nothing was started in the storage


async def test_a_version_that_does_not_exist_is_a_404(client, login, db, work) -> None:
    await start(client, login, db, work)
    assert (await client.post(URL, json=body(version=2))).status_code == 404


async def test_a_dataset_without_a_version_cannot_be_evaluated_on(client, login, db, work) -> None:
    await start(client, login, db, work)
    await create_dataset(client, "empty-set")
    response = await client.post(URL, json=body(dataset="ada/empty-set"))
    assert response.status_code == 422 and "has no version yet" in response.json()["detail"]


async def test_there_is_a_limit_to_the_evaluations_that_wait(client, login, db, work, monkeypatch) -> None:
    await start(client, login, db, work)
    monkeypatch.setattr(settings, "EVALUATIONS_MAX_OPEN", 2)
    await begin(client)
    await begin(client)
    assert (await client.post(URL, json=body())).status_code == 409


# ---- who may do what


async def test_the_people_who_can_edit_start_and_the_others_do_not(client, login, db, work) -> None:
    await start(client, login, db, work)
    await share(db, "ada/sentiment-fr", "u2", "maintainer")
    await share(db, "ada/sentiment-fr", "u3", "reader")
    login("u2", "bob")
    assert (await client.post(URL, json=body())).status_code == 201  # a maintainer (the dataset is public)
    login("u9", "root", admin=True)
    assert (await client.post(URL, json=body())).status_code == 201  # an admin
    for user_id in ("u3", "u4"):  # a reader, and somebody with no access (the model is public)
        login(user_id, "someone")
        assert (await client.post(URL, json=body())).status_code == 403
    login("u1", "ada")
    assert len((await client.get(URL)).json()) == 2


async def test_nothing_without_a_login(client, login, db, work) -> None:
    await start(client, login, db, work)
    app.dependency_overrides.pop(get_current_user, None)
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json=body())).status_code == 401


async def test_a_private_model_does_not_say_it_exists(client, login, db, work) -> None:
    await start(client, login, db, work, visibility="private")
    evaluation = await begin(client)
    login("u2", "bob")
    assert (await client.get(URL)).status_code == 404
    assert (await client.get(f"{URL}/{evaluation['id']}")).status_code == 404
    assert (await client.post(URL, json=body())).status_code == 404


async def test_only_the_people_who_can_edit_see_or_send_the_predictions(client, login, db, work, store) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    await share(db, "ada/sentiment-fr", "u3", "reader")
    for user_id in ("u3", "u4"):
        login(user_id, "someone")
        assert (await client.get(f"{URL}/{evaluation['id']}/upload")).status_code == 403
        assert (await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": [1]})).status_code == 403
        assert (await client.post(f"{URL}/{evaluation['id']}/upload/complete")).status_code == 403
    login("u1", "ada")
    assert (await client.get(f"{URL}/{evaluation['id']}/upload")).status_code == 200


async def test_a_dataset_the_person_cannot_read_looks_like_one_that_does_not_exist(client, login, db, work) -> None:
    await start(client, login, db, work)
    await create_dataset(client, "secret-set", visibility="private")
    await share(db, "ada/sentiment-fr", "u2", "maintainer")
    login("u2", "bob")
    unknown = await client.post(URL, json=body(dataset="ada/nothing"))
    hidden = await client.post(URL, json=body(dataset="ada/secret-set"))
    assert unknown.status_code == hidden.status_code == 422
    assert unknown.json()["detail"].replace("nothing", "X") == hidden.json()["detail"].replace("secret-set", "X")


async def test_nothing_a_client_sends_can_be_a_metric(client, login, db, work) -> None:
    """There is no route for values, and a body that carries some is not taken for them."""
    await start(client, login, db, work)
    evaluation = await begin(client, results={"accuracy": 1.0}, shown=["accuracy"], status="done", source="inference")
    assert evaluation["results"] == {} and evaluation["status"] == "uploading" and evaluation["source"] == "predictions"
    assert evaluation["shown"] == [] and evaluation["finished_at"] is None


# ---- how the predictions were made

HARDWARE = {
    "device": "gpu", "cpu": "AMD EPYC 7B13", "cpu_cores": 16, "ram_gb": 64.0, "os": "Linux 6.8",
    "gpus": [{"name": "NVIDIA A100", "memory_gb": 40}], "runtime": "onnxruntime 1.20, python 3.13",
}  # fmt: skip


async def test_the_time_and_the_hardware_are_kept_and_said_to_be_declared(client, login, db, work) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client, inference={"seconds": 12.5, "hardware": HARDWARE})
    assert evaluation["inference"]["seconds"] == 12.5 and evaluation["inference"]["origin"] == "declared"
    assert evaluation["inference"]["hardware"]["gpus"] == [{"name": "NVIDIA A100", "memory_gb": 40.0}]
    assert evaluation["inference"]["hardware"]["cpu_cores"] == 16 and evaluation["inference"]["ms_per_item"] is None
    login("u2", "bob")  # a reader sees it too
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["inference"]["hardware"]["device"] == "gpu"


async def test_the_time_for_one_item_comes_once_the_items_are_counted(client, login, db, work) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client, inference={"seconds": 12.5})
    await db.execute(update(ModelEvaluation).where(ModelEvaluation.id == evaluation["id"]).values(items=1000))
    await db.commit()
    seen = (await client.get(f"{URL}/{evaluation['id']}")).json()["inference"]
    assert seen["ms_per_item"] == 12.5 and seen["hardware"] is None  # 12.5 s for 1000 items


async def test_it_is_measured_only_when_the_platform_ran_the_model(client, login, db, work) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client, inference={"seconds": 3, "hardware": {"device": "cpu"}})
    await db.execute(update(ModelEvaluation).where(ModelEvaluation.id == evaluation["id"]).values(source="inference"))
    await db.commit()
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["inference"]["origin"] == "measured"


async def test_nothing_is_said_when_nothing_was_given(client, login, db, work) -> None:
    await start(client, login, db, work)
    assert (await begin(client))["inference"] is None
    assert (await begin(client, inference={}))["inference"] is None


@pytest.mark.parametrize(
    "inference",
    [
        {"seconds": -1},
        {"seconds": "slow"},
        {"seconds": 10**8},
        {"hardware": {"device": "quantum"}},
        {"hardware": {}},
        {"hardware": {"device": "cpu", "cpu_cores": 0}},
        {"hardware": {"device": "cpu", "ram_gb": -2}},
        {"hardware": {"device": "cpu", "cpu": "x" * 201}},
        {"hardware": {"device": "gpu", "gpus": [{"name": ""}]}},
        {"hardware": {"device": "gpu", "gpus": [{"name": "g"}] * 17}},
        {"hardware": {"device": "cpu", "secret": "x"}},
        {"energy": 3},
    ],
)
async def test_what_is_not_a_time_or_a_hardware_is_refused(client, login, db, work, inference) -> None:
    await start(client, login, db, work)
    assert (await client.post(URL, json=body(inference=inference))).status_code == 422
    assert (await client.get(URL)).json() == []


@pytest.mark.parametrize("value", ["NaN", "Infinity"])
async def test_a_time_that_is_not_a_number_is_a_422(client, login, db, work, value) -> None:
    await start(client, login, db, work)
    raw = (
        f'{{"version": 1, "task": "classification", "dataset": "{DATASET}", "split": "test", "target_column": "label", '
        f'"format": "jsonl", "size": 10, "inference": {{"seconds": {value}}}}}'
    )
    answer = await client.post(URL, content=raw, headers={"content-type": "application/json"})
    assert answer.status_code == 422


# ---- reading


async def computed(db: AsyncSession, evaluation_id: str, results: dict, shown: list[str], **fields) -> None:
    """What the worker does when it is done (it is a later issue): the result is written by the platform."""
    await db.execute(
        update(ModelEvaluation)
        .where(ModelEvaluation.id == evaluation_id)
        .values(status="done", results=results, shown=shown, finished_at=datetime.now(UTC), **fields)
    )
    await db.commit()


RESULT = {"accuracy": 0.9, "precision": 0.8, "recall": 0.7, "f1": 0.75, "auc": 0.95}


async def test_a_reader_sees_only_the_metrics_that_were_chosen(client, login, db, work) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    await computed(db, evaluation["id"], RESULT, ["f1"])
    login("u2", "bob")
    for seen in ((await client.get(URL)).json()[0], (await client.get(f"{URL}/{evaluation['id']}")).json()):
        assert (
            seen["results"] == {"f1": 0.75}
            and seen["hidden"] == 4
            and seen["shown"] == ["f1"]
            and seen["can_edit"] is False
        )
    login("u1", "ada")
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["results"] == RESULT


async def test_the_address_of_a_private_dataset_is_told_only_to_the_people_who_may_read_it(
    client, login, db, work
) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    await db.execute(update(Dataset).where(Dataset.name == "movie-reviews").values(visibility="private"))
    await db.commit()
    login("u2", "bob")
    seen = (await client.get(f"{URL}/{evaluation['id']}")).json()
    assert seen["dataset"] is None and seen["dataset_version"] is None and seen["split"] == "test"
    login("u1", "ada")
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["dataset"] == DATASET


async def test_a_dataset_that_is_deleted_leaves_the_evaluation_and_tells_its_address_to_the_editors_only(
    client, login, db, work
) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    assert (await client.delete(f"/api/datasets/{DATASET}")).status_code == 204
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["dataset"] == DATASET
    login("u2", "bob")
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["dataset"] is None
    stored = (await db.execute(select(ModelEvaluation))).scalar_one()
    assert stored.dataset_id is None and stored.dataset_address == DATASET


async def test_the_evaluations_come_newest_first_and_can_be_filtered(client, login, db, work) -> None:
    await start(client, login, db, work)
    first = await begin(client)
    second = await begin(client, task="regression")
    assert [e["id"] for e in (await client.get(URL)).json()] == [second["id"], first["id"]]
    assert [e["id"] for e in (await client.get(URL, params={"task": "regression"})).json()] == [second["id"]]
    assert [e["id"] for e in (await client.get(URL, params={"version": 1, "limit": 1, "offset": 1})).json()] == [
        first["id"]
    ]
    assert (await client.get(URL, params={"version": 2})).json() == []
    assert (await client.get(URL, params={"limit": 0})).status_code == 422


async def test_an_evaluation_of_another_model_is_not_found(client, login, db, work) -> None:
    await start(client, login, db, work)
    await create(client, "other")
    evaluation = await begin(client)
    assert (await client.get(f"{MODELS}/ada/other/evaluations/{evaluation['id']}")).status_code == 404
    assert (await client.delete(f"{MODELS}/ada/other/evaluations/{evaluation['id']}")).status_code == 404
    assert (await client.get(f"{URL}/not-an-id")).status_code == 422


# ---- changing, deleting, giving up


async def test_the_shown_metrics_are_changed_by_the_editors(client, login, db, work) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    await computed(db, evaluation["id"], RESULT, ["accuracy"])
    await share(db, "ada/sentiment-fr", "u3", "reader")
    changed = await client.put(f"{URL}/{evaluation['id']}/shown", json={"shown": ["auc", "auc", "recall"]})
    assert changed.status_code == 200 and changed.json()["shown"] == ["auc", "recall"]
    login("u3", "carol")
    assert (await client.put(f"{URL}/{evaluation['id']}/shown", json={"shown": []})).status_code == 403
    assert (await client.get(f"{URL}/{evaluation['id']}")).json()["results"] == {"recall": 0.7, "auc": 0.95}


async def test_a_metric_the_result_does_not_have_cannot_be_shown(client, login, db, work) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)  # nothing computed yet: it has no metric
    response = await client.put(f"{URL}/{evaluation['id']}/shown", json={"shown": ["accuracy"]})
    assert response.status_code == 422 and "accuracy cannot be shown" in response.json()["detail"]
    assert (await client.put(f"{URL}/{evaluation['id']}/shown", json={"shown": ["Not Valid"]})).status_code == 422


async def test_an_evaluation_is_deleted_by_the_editors_only_with_what_it_kept(client, login, db, work, store) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    await send(client, store, evaluation)
    key = (await db.execute(select(ModelEvaluation.predictions_key))).scalar_one()
    assert key in store.objects
    await share(db, "ada/sentiment-fr", "u3", "reader")
    login("u3", "carol")
    assert (await client.delete(f"{URL}/{evaluation['id']}")).status_code == 403
    login("u1", "ada")
    assert (await client.delete(f"{URL}/{evaluation['id']}")).status_code == 204
    assert (await client.delete(f"{URL}/{evaluation['id']}")).status_code == 404
    assert key not in store.objects and (await client.get(URL)).json() == []


async def test_giving_up_the_predictions_frees_the_parts_that_arrived(client, login, db, work, store) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    url = (await client.post(f"{URL}/{evaluation['id']}/upload/parts", json={"numbers": [1]})).json()["parts"][0]["url"]
    store.receive(url, PREDICTIONS)
    assert len(store.uploads) == 1
    assert (await client.delete(f"{URL}/{evaluation['id']}")).status_code == 204
    assert store.uploads == {}  # the parts that were received are not kept


# ---- the ones that were abandoned


async def test_predictions_that_never_arrive_are_given_up_with_their_parts(client, login, db, work, store) -> None:
    from app.services.factory import build_model_evaluations

    await start(client, login, db, work)
    abandoned = await begin(client)
    kept = await begin(client)
    url = (await client.post(f"{URL}/{abandoned['id']}/upload/parts", json={"numbers": [1]})).json()["parts"][0]["url"]
    store.receive(url, PREDICTIONS)
    await db.execute(
        update(ModelEvaluation)
        .where(ModelEvaluation.id == abandoned["id"])
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db.commit()
    assert await build_model_evaluations(db, store).expire_stale() == 1
    assert [e["id"] for e in (await client.get(URL)).json()] == [kept["id"]]
    assert len(store.uploads) == 1  # the other one is still going


async def test_the_sweep_of_the_worker_gives_them_up_too(client, login, db, work, store, monkeypatch) -> None:
    await start(client, login, db, work)
    abandoned = await begin(client)
    await db.execute(
        update(ModelEvaluation)
        .where(ModelEvaluation.id == abandoned["id"])
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db.commit()
    monkeypatch.setattr(settings, "WORKER_API_KEY", "worker-key-of-sixteen-characters")
    answer = await client.post(
        "/api/internal/dataset-uploads/expire", headers={"X-Api-Key": "worker-key-of-sixteen-characters"}
    )
    assert answer.status_code == 200 and answer.json() == {"expired": 1}
    assert (await client.get(URL)).json() == []


# ---- they go with what they are about


async def test_the_evaluations_go_with_their_version(client, login, db, work, registry) -> None:
    await start(client, login, db, work)
    await begin(client)
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr/versions/1")).status_code == 204
    assert (await db.execute(select(ModelEvaluation))).first() is None


async def test_the_evaluations_go_with_their_model(client, login, db, work, registry) -> None:
    await start(client, login, db, work)
    await begin(client)
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr")).status_code == 204
    assert (await db.execute(select(ModelEvaluation))).first() is None


async def test_the_database_refuses_what_cannot_be_right(client, login, db, work) -> None:
    await start(client, login, db, work)
    evaluation = await begin(client)
    bad = (
        {"status": "done"},  # done with no result
        {"source": "submitted"},  # nobody publishes what a person sends
        {"source": "measured"},
        {"predictions_format": "xml"},
        {"multipart_id": None},  # uploading with no upload
        {"items": -1},
    )
    for change in bad:
        with pytest.raises(IntegrityError):
            await db.execute(update(ModelEvaluation).where(ModelEvaluation.id == evaluation["id"]).values(**change))
            await db.flush()
        await db.rollback()
