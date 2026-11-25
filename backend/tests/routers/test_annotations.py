import hashlib

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Annotation
from tests.routers.test_dataset_files import TEST, TRAIN, part, push
from tests.routers.test_dataset_files import work as work  # the worker that reads the files of a dataset
from tests.routers.test_datasets import create as create_dataset
from tests.routers.test_datasets import share

DATASET = "ada/movie-reviews"
TASKS = f"/api/datasets/{DATASET}/tasks"


@pytest.fixture
async def ready(client: httpx2.AsyncClient, login, work) -> None:
    """A dataset of ada's with a train and a test split, read by the worker."""
    login("u1", "ada")
    await create_dataset(client, visibility="private")
    await push(client, part("train.csv", TRAIN), part("test.csv", TEST), address=f"/api/datasets/{DATASET}")
    await work()


async def make(client: httpx2.AsyncClient, **changes) -> dict:
    body = {
        "name": "sentiment",
        "type": "classification",
        "text_column": "text",
        "labels": [{"name": "pos"}, {"name": "neg"}],
    }
    response = await client.post(TASKS, json={**body, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def label(task: dict, name: str) -> str:
    return next(x["id"] for x in task["labels"] if x["name"] == name)


def answer_url(task: dict, split: str = "train", row: int = 0) -> str:
    return f"/api/tasks/{task['id']}/rows/{split}/{row}/annotation"


# ---- tasks


async def test_a_task_is_made_with_its_labels_in_order(client, ready) -> None:
    task = await make(client)
    assert task["dataset"] == DATASET
    assert task["status"] == "open"
    assert task["config"] == {"text_column": "text"}
    assert [x["name"] for x in task["labels"]] == ["pos", "neg"]
    assert task["can_edit"] and task["can_annotate"]
    assert (await client.get(f"/api/tasks/{task['id']}")).json() == task
    assert (await client.get(TASKS)).json() == [task]


async def test_a_task_needs_a_column_that_exists_and_a_known_kind(client, ready) -> None:
    for changes in ({"text_column": "nope"}, {"type": "ner"}, {"type": "unknown"}):
        response = await client.post(
            TASKS, json={"name": "x", "type": "classification", "text_column": "text", **changes}
        )
        assert response.status_code in (422,), (changes, response.text)


async def test_two_labels_cannot_have_the_same_name(client, ready) -> None:
    response = await client.post(
        TASKS,
        json={
            "name": "x",
            "type": "classification",
            "text_column": "text",
            "labels": [{"name": "Pos"}, {"name": "pos"}],
        },
    )
    assert response.status_code == 422


async def test_the_name_of_a_task_is_unique_in_its_dataset(client, ready) -> None:
    await make(client)
    response = await client.post(TASKS, json={"name": "sentiment", "type": "classification", "text_column": "text"})
    assert response.status_code == 409


async def test_a_dataset_without_rows_has_nothing_to_annotate(client, login) -> None:
    login("u1", "ada")
    await create_dataset(client)
    response = await client.post(TASKS, json={"name": "x", "type": "classification", "text_column": "text"})
    assert response.status_code == 422


async def test_a_task_is_renamed_closed_and_deleted_with_its_answers(client, ready, db: AsyncSession) -> None:
    task = await make(client)
    await client.put(answer_url(task), json={"label_id": label(task, "pos")})
    renamed = await client.patch(f"/api/tasks/{task['id']}", json={"name": "tone", "status": "closed"})
    assert (renamed.json()["name"], renamed.json()["status"]) == ("tone", "closed")
    assert (await client.delete(f"/api/tasks/{task['id']}")).status_code == 204
    assert (await client.get(f"/api/tasks/{task['id']}")).status_code == 404
    assert (await db.execute(select(func.count()).select_from(Annotation))).scalar_one() == 0


# ---- labels


async def test_a_label_is_added_renamed_and_deleted_without_losing_answers(client, ready) -> None:
    task = await make(client)
    pos = label(task, "pos")
    await client.put(answer_url(task), json={"label_id": pos})
    added = await client.post(f"/api/tasks/{task['id']}/labels", json={"name": "mixed", "description": "both"})
    assert added.status_code == 201 and added.json()["position"] == 2
    renamed = await client.patch(f"/api/tasks/{task['id']}/labels/{pos}", json={"name": "positive"})
    assert renamed.json()["id"] == pos
    assert (await client.delete(f"/api/tasks/{task['id']}/labels/{pos}")).status_code == 204
    assert [x["name"] for x in (await client.get(f"/api/tasks/{task['id']}")).json()["labels"]] == ["neg", "mixed"]
    # the answer is still there, and the name is free again
    rows = (await client.get(f"/api/tasks/{task['id']}/rows")).json()["rows"]
    assert rows[0]["mine"]["label_id"] == pos
    assert (await client.post(f"/api/tasks/{task['id']}/labels", json={"name": "positive"})).status_code == 201
    assert (await client.post(f"/api/tasks/{task['id']}/labels", json={"name": "MIXED"})).status_code == 422


# ---- answering


async def test_the_rows_come_with_their_text_and_my_answer(client, ready) -> None:
    task = await make(client)
    page = (await client.get(f"/api/tasks/{task['id']}/rows", params={"limit": 2})).json()
    assert (page["split"], page["total"], page["splits"]) == ("train", 5, ["train", "test"])
    assert [(r["row_index"], r["text"], r["mine"]) for r in page["rows"]] == [(0, "great", None), (1, "awful", None)]
    test = (await client.get(f"/api/tasks/{task['id']}/rows", params={"split": "test", "offset": 1})).json()
    assert [r["text"] for r in test["rows"]] == ["horrible"]


async def test_an_answer_is_made_replaced_and_taken_back(client, ready, db: AsyncSession) -> None:
    task = await make(client)
    first = await client.put(answer_url(task, row=1), json={"label_id": label(task, "pos"), "reason": " why "})
    assert first.status_code == 200, first.text
    assert (first.json()["status"], first.json()["source"], first.json()["version_number"]) == ("submitted", "human", 1)
    assert first.json()["reason"] == "why"
    # the same call twice, then another label: still one answer
    await client.put(answer_url(task, row=1), json={"label_id": label(task, "pos"), "reason": " why "})
    changed = await client.put(answer_url(task, row=1), json={"label_id": label(task, "neg")})
    assert changed.json()["label_id"] == label(task, "neg") and changed.json()["reason"] is None
    assert (await db.execute(select(func.count()).select_from(Annotation))).scalar_one() == 1
    page = (await client.get(f"/api/tasks/{task['id']}/rows", params={"limit": 2})).json()
    assert page["rows"][0]["mine"] is None and page["rows"][1]["mine"]["label_id"] == label(task, "neg")
    assert (await client.delete(answer_url(task, row=1))).status_code == 204
    assert (await db.execute(select(func.count()).select_from(Annotation))).scalar_one() == 0


async def test_an_answer_keeps_a_fingerprint_of_the_text(client, ready, db: AsyncSession) -> None:
    task = await make(client)
    await client.put(answer_url(task), json={"label_id": label(task, "pos")})
    stored = (await db.execute(select(Annotation))).scalar_one()
    assert stored.text_sha256 == hashlib.sha256(b"great").hexdigest()


async def test_a_draft_may_have_no_label_but_a_submitted_answer_needs_one(client, ready) -> None:
    task = await make(client)
    draft = await client.put(answer_url(task), json={"status": "draft"})
    assert draft.status_code == 200 and draft.json()["label_id"] is None
    assert (await client.put(answer_url(task), json={"status": "submitted"})).status_code == 422


async def test_an_answer_needs_a_label_of_the_task_and_a_row_of_the_dataset(client, ready) -> None:
    task = await make(client)
    other = await make(client, name="other")
    assert (await client.put(answer_url(task), json={"label_id": label(other, "pos")})).status_code == 422
    deleted = label(task, "neg")
    await client.delete(f"/api/tasks/{task['id']}/labels/{deleted}")
    assert (await client.put(answer_url(task), json={"label_id": deleted})).status_code == 422
    good = label(task, "pos")
    assert (await client.put(answer_url(task, row=99), json={"label_id": good})).status_code == 404
    assert (await client.put(answer_url(task, split="nope"), json={"label_id": good})).status_code == 404


async def test_nothing_is_answered_in_a_closed_task(client, ready) -> None:
    task = await make(client)
    await client.patch(f"/api/tasks/{task['id']}", json={"status": "closed"})
    assert (await client.put(answer_url(task), json={"label_id": label(task, "pos")})).status_code == 409
    assert (await client.delete(answer_url(task))).status_code == 409


async def test_the_progress_counts_the_answers_of_everybody(client, ready, db: AsyncSession, login) -> None:
    task = await make(client)
    await share(db, DATASET, "u2", "annotator")
    await client.put(answer_url(task, row=0), json={"label_id": label(task, "pos")})
    await client.put(answer_url(task, row=1), json={"status": "draft"})
    login("u2", "bob")
    await client.put(answer_url(task, row=0), json={"label_id": label(task, "neg")})
    progress = (await client.get(f"/api/tasks/{task['id']}/progress")).json()
    assert progress["total"] == 7
    assert (progress["mine"], progress["mine_submitted"]) == (1, 1)
    assert (progress["answered_rows"], progress["annotators"]) == (2, 2)
    assert {x["label_id"]: x["answers"] for x in progress["by_label"]} == {label(task, "pos"): 1, label(task, "neg"): 1}
    login("u1", "ada")
    assert (await client.get(f"/api/tasks/{task['id']}/progress")).json()["mine"] == 2


# ---- who may do what


async def test_each_role_does_what_it_may(client, ready, db: AsyncSession, login) -> None:
    task = await make(client)
    await share(db, DATASET, "u2", "reader")
    await share(db, DATASET, "u3", "annotator")
    pos = label(task, "pos")

    login("u2", "bob")  # a reader sees, answers nothing, changes nothing
    seen = (await client.get(f"/api/tasks/{task['id']}")).json()
    assert (seen["can_edit"], seen["can_annotate"]) == (False, False)
    assert (await client.get(f"/api/tasks/{task['id']}/rows")).status_code == 200
    assert (await client.put(answer_url(task), json={"label_id": pos})).status_code == 403
    assert (await client.patch(f"/api/tasks/{task['id']}", json={"status": "closed"})).status_code == 403
    assert (
        await client.post(TASKS, json={"name": "x", "type": "classification", "text_column": "text"})
    ).status_code == 403

    login("u3", "eve")  # an annotator answers, and changes nothing
    assert (await client.put(answer_url(task), json={"label_id": pos})).status_code == 200
    assert (await client.post(f"/api/tasks/{task['id']}/labels", json={"name": "x"})).status_code == 403
    assert (await client.delete(f"/api/tasks/{task['id']}")).status_code == 403


async def test_a_private_dataset_task_looks_like_it_does_not_exist(client, ready, login) -> None:
    task = await make(client)
    login("u9", "mallory")
    assert (await client.get(f"/api/tasks/{task['id']}")).status_code == 404
    assert (await client.get(f"/api/tasks/{task['id']}/rows")).status_code == 404
    assert (await client.put(answer_url(task), json={"status": "draft"})).status_code == 404
    assert (await client.get(TASKS)).status_code == 404
