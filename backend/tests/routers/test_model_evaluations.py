import httpx2
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, ModelEvaluation
from tests.routers.test_datasets import create as create_dataset
from tests.routers.test_models import MODELS, create, register, share

URL = f"{MODELS}/ada/sentiment-fr/evaluations"
RESULT = {"accuracy": 0.9, "precision": 0.8, "recall": 0.7, "f1": 0.75, "auc": 0.95}


async def start(client: httpx2.AsyncClient, login, db: AsyncSession, **model) -> None:
    """A model of ada's with one version."""
    login("u1", "ada")
    await create(client, **model)
    await register(db, "ada/sentiment-fr")


def body(**changes) -> dict:
    return {"version": 1, "task": "classification", "results": RESULT, **changes}


async def send(client: httpx2.AsyncClient, **changes) -> dict:
    response = await client.post(URL, json=body(**changes))
    assert response.status_code == 201, response.text
    return response.json()


# ---- the metrics


async def test_the_metrics_of_every_task_are_listed_for_a_person_who_is_logged_in(client, login) -> None:
    assert (await client.get("/api/metrics")).status_code == 401
    login("u1", "ada")
    listed = {t["task"]: t for t in (await client.get("/api/metrics")).json()}
    assert [m["id"] for m in listed["classification"]["metrics"]] == ["accuracy", "precision", "recall", "f1", "auc"]
    assert listed["classification"]["default_shown"] == ["accuracy", "precision"]
    mae = next(m for m in listed["regression"]["metrics"] if m["id"] == "mae")
    assert (mae["higher"], mae["primary"]) == (False, True)


# ---- sending a result


async def test_a_result_that_is_sent_is_kept_as_sent(client, login, db) -> None:
    await start(client, login, db)
    evaluation = await send(client, note="cross-validation, 5 folds", items=1200, split="test", target_column="label")
    assert evaluation["source"] == "submitted" and evaluation["status"] == "done"
    assert (evaluation["version"], evaluation["task"], evaluation["items"], evaluation["split"]) == (
        1,
        "classification",
        1200,
        "test",
    )
    assert evaluation["note"] == "cross-validation, 5 folds" and evaluation["created_by_username"] == "ada"
    assert evaluation["results"] == RESULT and evaluation["hidden"] == 0 and evaluation["can_edit"] is True
    assert evaluation["shown"] == ["accuracy", "precision"]  # the main one and the next, unless the author chooses
    assert evaluation["finished_at"] is not None and evaluation["error"] is None


async def test_the_author_chooses_which_metrics_are_shown(client, login, db) -> None:
    await start(client, login, db)
    evaluation = await send(client, shown=["f1", "recall", "f1"])
    assert evaluation["shown"] == ["f1", "recall"]  # no metric twice


async def test_only_some_metrics_may_be_sent(client, login, db) -> None:
    await start(client, login, db)
    evaluation = await send(client, results={"f1": 0.5})
    assert evaluation["results"] == {"f1": 0.5} and evaluation["shown"] == ["f1"]  # the first ones it has


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"results": {}}, "at least one metric"),
        ({"results": {"wer": 0.1}}, "not a metric of classification"),
        ({"results": {"accuracy": True}}, ""),
        ({"results": {"accuracy": "high"}}, ""),
        ({"results": {f"m{i}": 0.1 for i in range(51)}}, ""),
        ({"results": {"Accuracy": 0.1}}, ""),
        ({"task": "ner"}, "This model does not do ner"),
        ({"task": "classification", "shown": ["f1"], "results": {"accuracy": 0.5}}, "f1 cannot be shown"),
        ({"dataset": "ada/nothing"}, "No dataset ada/nothing"),
        ({"dataset": "not an address"}, ""),
        ({"items": -1}, ""),
        ({"note": "x" * 1001}, ""),
        ({"version": 0}, ""),
    ],
)
async def test_what_is_not_valid_is_refused(client, login, db, changes: dict, message: str) -> None:
    await start(client, login, db)
    response = await client.post(URL, json=body(**changes))
    assert response.status_code == 422, response.text
    if message:
        assert message in response.json()["detail"]
    assert (await client.get(URL)).json() == []


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
async def test_nan_and_infinity_are_not_metrics(client, login, db, value: str) -> None:
    await start(client, login, db)
    raw = f'{{"version": 1, "task": "classification", "results": {{"accuracy": {value}}}}}'
    response = await client.post(URL, content=raw, headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert (await client.get(URL)).json() == []


async def test_a_version_that_does_not_exist_is_a_404(client, login, db) -> None:
    await start(client, login, db)
    assert (await client.post(URL, json=body(version=2))).status_code == 404


# ---- who may send, who may read


async def test_the_people_who_can_edit_send_and_the_others_do_not(client, login, db) -> None:
    await start(client, login, db)
    await share(db, "ada/sentiment-fr", "u2", "maintainer")
    await share(db, "ada/sentiment-fr", "u3", "reader")
    login("u2", "bob")
    assert (await client.post(URL, json=body())).status_code == 201  # a maintainer
    login("u9", "root", admin=True)
    assert (await client.post(URL, json=body())).status_code == 201  # an admin
    for user_id in ("u3", "u4"):  # a reader, and somebody with no access (the model is public)
        login(user_id, "someone")
        assert (await client.post(URL, json=body())).status_code == 403
    login("u1", "ada")
    assert len((await client.get(URL)).json()) == 2  # only the two that were allowed


async def test_nothing_without_a_login(client, login, db) -> None:
    await start(client, login, db)
    from app.auth.deps import get_current_user
    from app.main import app

    app.dependency_overrides.pop(get_current_user, None)
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json=body())).status_code == 401


async def test_a_private_model_does_not_say_it_exists(client, login, db) -> None:
    await start(client, login, db, visibility="private")
    evaluation = await send(client)
    login("u2", "bob")
    assert (await client.get(URL)).status_code == 404
    assert (await client.get(f"{URL}/{evaluation['id']}")).status_code == 404
    assert (await client.post(URL, json=body())).status_code == 404


async def test_a_reader_sees_only_the_metrics_that_were_chosen(client, login, db) -> None:
    await start(client, login, db)
    sent = await send(client, shown=["f1"])
    login("u2", "bob")
    for seen in ((await client.get(URL)).json()[0], (await client.get(f"{URL}/{sent['id']}")).json()):
        assert seen["results"] == {"f1": 0.75} and seen["hidden"] == 4 and seen["shown"] == ["f1"]
        assert seen["can_edit"] is False
    login("u1", "ada")
    assert (await client.get(f"{URL}/{sent['id']}")).json()["results"] == RESULT  # the author sees them all


async def test_nothing_chosen_means_nothing_for_the_others(client, login, db) -> None:
    await start(client, login, db)
    sent = await send(client, shown=[])
    login("u2", "bob")
    seen = (await client.get(f"{URL}/{sent['id']}")).json()
    assert seen["results"] == {} and seen["hidden"] == 5


# ---- the dataset


async def test_the_address_of_a_private_dataset_is_told_only_to_the_people_who_may_read_it(client, login, db) -> None:
    await start(client, login, db)
    await create_dataset(client, "secret-set", visibility="private")
    await create_dataset(client, "open-set")
    private = await send(client, dataset="ada/secret-set", dataset_version=2, split="test")
    public = await send(client, dataset="ada/open-set")
    assert private["dataset"] == "ada/secret-set" and private["dataset_version"] == 2
    login("u2", "bob")
    seen = {e["id"]: e for e in (await client.get(URL)).json()}
    assert seen[private["id"]]["dataset"] is None and seen[private["id"]]["dataset_version"] is None
    assert seen[private["id"]]["split"] == "test"  # the rest of the evaluation is not a secret
    assert seen[public["id"]]["dataset"] == "ada/open-set"


async def test_a_dataset_the_sender_cannot_read_looks_like_one_that_does_not_exist(client, login, db) -> None:
    await start(client, login, db)
    await create_dataset(client, "secret-set", visibility="private")
    await share(db, "ada/sentiment-fr", "u2", "maintainer")
    login("u2", "bob")
    unknown = await client.post(URL, json=body(dataset="ada/nothing"))
    hidden = await client.post(URL, json=body(dataset="ada/secret-set"))
    assert unknown.status_code == hidden.status_code == 422
    assert unknown.json()["detail"].replace("nothing", "X") == hidden.json()["detail"].replace("secret-set", "X")


async def test_a_dataset_that_is_deleted_leaves_the_evaluation_and_tells_its_address_to_the_editors_only(
    client, login, db
) -> None:
    await start(client, login, db)
    await create_dataset(client, "open-set")
    sent = await send(client, dataset="ada/open-set")
    assert (await client.delete("/api/datasets/ada/open-set")).status_code == 204
    kept = (await client.get(f"{URL}/{sent['id']}")).json()
    assert kept["dataset"] == "ada/open-set"  # the editor still knows what it was
    login("u2", "bob")
    assert (await client.get(f"{URL}/{sent['id']}")).json()["dataset"] is None
    stored = (await db.execute(select(ModelEvaluation))).scalar_one()
    assert stored.dataset_id is None and stored.dataset_address == "ada/open-set"
    assert (await db.execute(select(Dataset))).first() is None


# ---- listing


async def test_the_evaluations_come_newest_first_and_can_be_filtered(client, login, db) -> None:
    await start(client, login, db, tasks=["classification", "regression"])
    first = await send(client)
    second = await send(client, task="regression", results={"mae": 1.5, "r2": 0.4})
    assert [e["id"] for e in (await client.get(URL)).json()] == [second["id"], first["id"]]
    assert [e["id"] for e in (await client.get(URL, params={"task": "regression"})).json()] == [second["id"]]
    assert [e["id"] for e in (await client.get(URL, params={"version": 1, "limit": 1, "offset": 1})).json()] == [
        first["id"]
    ]
    assert (await client.get(URL, params={"version": 2})).json() == []
    assert (await client.get(URL, params={"limit": 0})).status_code == 422


async def test_an_evaluation_of_another_model_is_not_found(client, login, db) -> None:
    await start(client, login, db)
    await create(client, "other")
    sent = await send(client)
    assert (await client.get(f"{MODELS}/ada/other/evaluations/{sent['id']}")).status_code == 404
    assert (await client.delete(f"{MODELS}/ada/other/evaluations/{sent['id']}")).status_code == 404
    assert (await client.get(f"{URL}/not-an-id")).status_code == 422


# ---- changing and deleting


async def test_the_shown_metrics_are_changed_by_the_editors(client, login, db) -> None:
    await start(client, login, db)
    sent = await send(client)
    await share(db, "ada/sentiment-fr", "u3", "reader")
    changed = await client.put(f"{URL}/{sent['id']}/shown", json={"shown": ["auc", "auc", "recall"]})
    assert changed.status_code == 200 and changed.json()["shown"] == ["auc", "recall"]
    login("u3", "carol")
    assert (await client.put(f"{URL}/{sent['id']}/shown", json={"shown": []})).status_code == 403
    assert (await client.get(f"{URL}/{sent['id']}")).json()["results"] == {"recall": 0.7, "auc": 0.95}


async def test_a_metric_the_result_does_not_have_cannot_be_shown(client, login, db) -> None:
    await start(client, login, db)
    sent = await send(client, results={"f1": 0.5})
    response = await client.put(f"{URL}/{sent['id']}/shown", json={"shown": ["accuracy"]})
    assert response.status_code == 422 and "accuracy cannot be shown" in response.json()["detail"]
    assert (await client.put(f"{URL}/{sent['id']}/shown", json={"shown": ["Not Valid"]})).status_code == 422


async def test_an_evaluation_is_deleted_by_the_editors_only(client, login, db) -> None:
    await start(client, login, db)
    sent = await send(client)
    await share(db, "ada/sentiment-fr", "u3", "reader")
    login("u3", "carol")
    assert (await client.delete(f"{URL}/{sent['id']}")).status_code == 403
    login("u1", "ada")
    assert (await client.delete(f"{URL}/{sent['id']}")).status_code == 204
    assert (await client.delete(f"{URL}/{sent['id']}")).status_code == 404
    assert (await client.get(URL)).json() == []


# ---- they go with what they are about


async def test_the_evaluations_go_with_their_version(client, login, db, registry) -> None:
    await start(client, login, db)
    await send(client)
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr/versions/1")).status_code == 204
    assert (await db.execute(select(ModelEvaluation))).first() is None


async def test_the_evaluations_go_with_their_model(client, login, db, registry) -> None:
    await start(client, login, db)
    await send(client)
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr")).status_code == 204
    assert (await db.execute(select(ModelEvaluation))).first() is None


async def test_the_database_refuses_a_result_that_is_not_finished_or_empty(client, login, db) -> None:
    from sqlalchemy.exc import IntegrityError

    await start(client, login, db)
    sent = await send(client)
    for change in ({"status": "running"}, {"results": {}}, {"source": "other"}):
        with pytest.raises(IntegrityError):
            await db.execute(update(ModelEvaluation).where(ModelEvaluation.id == sent["id"]).values(**change))
            await db.flush()
        await db.rollback()
