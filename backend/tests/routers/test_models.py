import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.config import settings
from app.main import app
from app.models import Model, ModelFile, ModelMember, ModelVersion
from tests.conftest import MemoryStore

MODELS = "/api/models"


async def create(client: httpx2.AsyncClient, name: str = "sentiment-fr", **fields) -> dict:
    """Creates a model as the logged-in user and returns it (the call must succeed)."""
    body = {"name": name, "tasks": ["classification"], "inputs": ["text"], **fields}
    response = await client.post(MODELS, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _model(db: AsyncSession, address: str) -> Model:
    owner, name = address.split("/")
    return (await db.execute(select(Model).where(Model.owner == owner, Model.name == name))).scalar_one()


async def share(db: AsyncSession, address: str, user_id: str, role: str) -> None:
    model = await _model(db, address)
    db.add(ModelMember(model_id=model.id, user_id=user_id, role=role, added_by="u1"))
    await db.commit()


async def register(db: AsyncSession, address: str, *, key: str | None = None) -> None:
    """A version that MLflow knows (and, if `key` is given, one file of it in the storage)."""
    model = await _model(db, address)
    version = ModelVersion(
        model_id=model.id,
        number=1,
        mlflow_name=f"{model.owner}~{model.name}",
        mlflow_version="1",
        created_by="u1",
        created_by_username="ada",
    )
    db.add(version)
    await db.flush()
    if key:
        db.add(
            ModelFile(
                version_id=version.id,
                path="weights.bin",
                size_bytes=3,
                content_type="application/octet-stream",
                storage_key=key,
            )
        )
    await db.commit()


# ---- creating


async def test_a_model_is_created_in_the_name_of_its_creator(client, login, registry) -> None:
    login("u1", "Ada")
    model = await create(
        client,
        description=" Sentiment. ",
        tasks=["classification", "ner", "classification"],
        inputs=["text"],
        library="transformers",
        languages=["fr", "en"],
        license="apache-2.0",
        tags=["NLP", " nlp ", "sentiment"],
        card="# Sentiment",
        parameters=110_000_000,
        trained_on=["ada/movie-reviews"],
        code_url="https://github.com/ada/sentiment",
    )
    assert (model["owner"], model["name"]) == ("ada", "sentiment-fr")
    assert model["tasks"] == ["classification", "ner"]  # without duplicates
    assert model["tags"] == ["nlp", "sentiment"]  # lowercase, without duplicates
    assert model["description"] == " Sentiment. "  # the text is kept as it was sent
    assert (model["library"], model["languages"], model["parameters"]) == ("transformers", ["fr", "en"], 110_000_000)
    assert model["trained_on"] == ["ada/movie-reviews"]
    assert (model["visibility"], model["downloads"], model["likes"], model["liked"]) == ("public", 0, 0, False)
    assert (model["version"], model["size_bytes"], model["can_edit"], model["card"]) == (0, 0, True, "# Sentiment")
    assert (model["created_by"], model["created_by_username"]) == ("u1", "Ada")
    assert registry.calls == []  # MLflow is not needed to make a model


async def test_a_model_can_be_created_while_mlflow_is_down(client, login, registry) -> None:
    login()
    registry.down = True
    await create(client)


async def test_the_same_name_is_refused_for_the_same_person_only(client, login) -> None:
    login("u1", "ada")
    await create(client)
    assert (
        await client.post(MODELS, json={"name": "sentiment-fr", "tasks": ["ner"], "inputs": ["text"]})
    ).status_code == 409
    login("u2", "bob")
    assert (await create(client))["owner"] == "bob"


async def test_nothing_is_created_without_a_login(client) -> None:
    assert (await client.post(MODELS, json={"name": "x", "tasks": ["ner"], "inputs": ["text"]})).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"tasks": ["ner"], "inputs": ["text"]},  # no name
        {"name": "x", "inputs": ["text"]},  # no task
        {"name": "x", "tasks": ["ner"]},  # no input
        {"name": "x", "tasks": [], "inputs": ["text"]},
        {"name": "x", "tasks": ["ner"], "inputs": []},
        {"name": "x", "tasks": ["dancing"], "inputs": ["text"]},
        {"name": "x", "tasks": ["ner"], "inputs": ["smell"]},
        {"name": "Has Capitals", "tasks": ["ner"], "inputs": ["text"]},
        {"name": "a/b", "tasks": ["ner"], "inputs": ["text"]},
        {"name": "a~b", "tasks": ["ner"], "inputs": ["text"]},  # `~` is what separates the address in MLflow
        {"name": "x" * 101, "tasks": ["ner"], "inputs": ["text"]},
        {"name": "x", "tasks": ["ner"], "inputs": ["text"], "visibility": "secret"},
        {"name": "x", "tasks": ["ner"], "inputs": ["text"], "parameters": -1},
        {"name": "x", "tasks": ["ner"], "inputs": ["text"], "trained_on": ["not an address"]},
        {"name": "x", "tasks": ["ner"], "inputs": ["text"], "tags": ["t"] * 21},
    ],
)
async def test_what_is_not_valid_is_refused(client, login, body: dict) -> None:
    login()
    assert (await client.post(MODELS, json=body)).status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/ada/x",  # not https
        "https://evil.example/ada/x",
        "https://github.com.evil.example/ada/x",
        "https://user:pw@github.com/ada/x",
        "file:///etc/passwd",
        "github.com/ada/x",
    ],
)
async def test_the_code_must_be_at_an_allowed_host(client, login, url: str) -> None:
    login()
    body = {"name": "x", "tasks": ["ner"], "inputs": ["text"], "code_url": url}
    assert (await client.post(MODELS, json=body)).status_code == 422


@pytest.mark.parametrize("url", ["https://github.com/ada/x", "https://GitLab.com/ada/x/-/tree/main"])
async def test_the_code_can_be_at_github_or_gitlab(client, login, url: str) -> None:
    login()
    assert (await create(client, code_url=url))["code_url"] == url


# ---- reading


async def test_a_public_model_is_read_by_everybody_who_is_logged_in(client, login) -> None:
    login("u1", "ada")
    await create(client)
    login("u2", "bob")
    model = (await client.get(f"{MODELS}/ada/sentiment-fr")).json()
    assert (model["name"], model["can_edit"]) == ("sentiment-fr", False)


async def test_the_address_is_read_in_lowercase(client, login) -> None:
    login()
    await create(client)
    assert (await client.get(f"{MODELS}/ADA/Sentiment-FR")).status_code == 200


async def test_nothing_is_read_without_a_login(client, login) -> None:
    login()
    await create(client)
    app.dependency_overrides.pop(get_current_user, None)  # logged out
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).status_code == 401
    assert (await client.get(MODELS)).status_code == 401


async def test_a_private_model_looks_like_it_does_not_exist_to_a_stranger(client, login) -> None:
    login("u1", "ada")
    await create(client, visibility="private")
    login("u2", "bob")
    private = await client.get(f"{MODELS}/ada/sentiment-fr")
    missing = await client.get(f"{MODELS}/ada/nothing-here")
    assert (private.status_code, private.json()) == (missing.status_code, missing.json())
    assert private.status_code == 404
    # everything else answers the same: no way to tell
    for call in (
        client.patch(f"{MODELS}/ada/sentiment-fr", json={"description": "x"}),
        client.delete(f"{MODELS}/ada/sentiment-fr"),
        client.put(f"{MODELS}/ada/sentiment-fr/like"),
        client.get(f"{MODELS}/ada/sentiment-fr/members"),
        client.put(f"{MODELS}/ada/sentiment-fr/members/u3", json={"role": "reader"}),
    ):
        assert (await call).status_code == 404


@pytest.mark.parametrize(("role", "can_edit"), [("reader", False), ("maintainer", True)])
async def test_a_member_reads_a_private_model(client, login, db, role: str, can_edit: bool) -> None:
    login("u1", "ada")
    await create(client, visibility="private")
    await share(db, "ada/sentiment-fr", "u2", role)
    login("u2", "bob")
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).json()["can_edit"] is can_edit


async def test_an_admin_reads_and_edits_everything(client, login) -> None:
    login("u1", "ada")
    await create(client, visibility="private")
    login("u9", "root", admin=True)
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).json()["can_edit"] is True


# ---- changing


async def test_the_creator_changes_a_model(client, login) -> None:
    login()
    created = await create(client)
    response = await client.patch(
        f"{MODELS}/ada/sentiment-fr",
        json={"description": "New", "tags": ["B", "b"], "visibility": "private", "library": "pytorch"},
    )
    model = response.json()
    assert (model["description"], model["tags"], model["visibility"], model["library"]) == (
        "New",
        ["b"],
        "private",
        "pytorch",
    )
    assert model["updated_at"] > created["updated_at"]
    assert model["tasks"] == created["tasks"]  # untouched


async def test_the_code_and_the_parameters_can_be_taken_off(client, login) -> None:
    login()
    await create(client, code_url="https://github.com/ada/x", parameters=5)
    model = (await client.patch(f"{MODELS}/ada/sentiment-fr", json={"code_url": None, "parameters": None})).json()
    assert (model["code_url"], model["parameters"]) == (None, None)


async def test_the_new_code_is_checked_too(client, login) -> None:
    login()
    await create(client)
    assert (
        await client.patch(f"{MODELS}/ada/sentiment-fr", json={"code_url": "https://evil.example/x"})
    ).status_code == 422


@pytest.mark.parametrize("user", ["maintainer", "admin"])
async def test_a_maintainer_and_an_admin_change_a_model(client, login, db, user: str) -> None:
    login("u1", "ada")
    await create(client)
    if user == "admin":
        login("u9", "root", admin=True)
    else:
        await share(db, "ada/sentiment-fr", "u2", "maintainer")
        login("u2", "bob")
    assert (await client.patch(f"{MODELS}/ada/sentiment-fr", json={"description": "x"})).status_code == 200


async def test_a_reader_and_a_stranger_cannot_change_a_public_model(client, login, db) -> None:
    login("u1", "ada")
    await create(client)
    await share(db, "ada/sentiment-fr", "u2", "reader")
    for user_id in ("u2", "u3"):
        login(user_id, "someone")
        assert (await client.patch(f"{MODELS}/ada/sentiment-fr", json={"description": "x"})).status_code == 403
        assert (await client.delete(f"{MODELS}/ada/sentiment-fr")).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": "other"},
        {"owner": "bob"},
        {"tasks": ["ner"]},
        {"inputs": ["image"]},
        {"description": None},
        {"visibility": "secret"},
        {"parameters": -3},
    ],
)
async def test_what_cannot_be_changed_is_refused(client, login, body: dict) -> None:
    login()
    await create(client)
    assert (await client.patch(f"{MODELS}/ada/sentiment-fr", json=body)).status_code == 422


# ---- deleting


async def test_the_creator_deletes_a_model(client, login, registry) -> None:
    login()
    await create(client)
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr")).status_code == 204
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).status_code == 404
    assert registry.calls == []  # MLflow never knew it


async def test_deleting_a_model_deletes_it_in_mlflow_and_its_files(client, login, db, registry, store) -> None:
    login()
    await create(client)
    await register(db, "ada/sentiment-fr", key="models/ab/abc")
    await store.put("models/ab/abc", b"abc", "application/octet-stream")
    await registry.create_model("ada~sentiment-fr")
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr")).status_code == 204
    assert "ada~sentiment-fr" not in registry.models
    assert await store.get("models/ab/abc") is None


async def test_nothing_is_deleted_while_mlflow_does_not_answer(client, login, db, registry, store: MemoryStore) -> None:
    login()
    await create(client)
    await register(db, "ada/sentiment-fr", key="models/ab/abc")
    await store.put("models/ab/abc", b"abc", "application/octet-stream")
    registry.down = True
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr")).status_code == 503
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).status_code == 200
    assert await store.get("models/ab/abc") is not None
    registry.down = False  # and it can be done again
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr")).status_code == 204


async def test_a_deleted_model_takes_its_members_and_likes_with_it(client, login, db) -> None:
    login()
    await create(client)
    await share(db, "ada/sentiment-fr", "u2", "reader")
    await client.put(f"{MODELS}/ada/sentiment-fr/like")
    await client.delete(f"{MODELS}/ada/sentiment-fr")
    assert (await db.execute(select(ModelMember))).first() is None
    await create(client)  # and the name is free again
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).json()["likes"] == 0


# ---- liking


async def test_liking_twice_counts_once(client, login) -> None:
    login("u1", "ada")
    await create(client)
    login("u2", "bob")
    assert (await client.put(f"{MODELS}/ada/sentiment-fr/like")).json() == {"liked": True, "likes": 1}
    assert (await client.put(f"{MODELS}/ada/sentiment-fr/like")).json() == {"liked": True, "likes": 1}
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).json()["liked"] is True
    login("u3", "eve")
    assert (await client.put(f"{MODELS}/ada/sentiment-fr/like")).json()["likes"] == 2
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr/like")).json() == {"liked": False, "likes": 1}
    assert (await client.delete(f"{MODELS}/ada/sentiment-fr/like")).json() == {"liked": False, "likes": 1}


# ---- the list


async def test_the_list_is_paginated_and_counted(client, login) -> None:
    login()
    for index in range(5):
        await create(client, f"m{index}")
    page = (await client.get(MODELS, params={"limit": 2, "offset": 2, "sort": "updated"})).json()
    assert (page["total"], page["limit"], page["offset"], len(page["items"])) == (5, 2, 2, 2)
    assert "card" not in page["items"][0]
    assert (await client.get(MODELS, params={"limit": 0})).status_code == 422
    assert (await client.get(MODELS, params={"limit": settings.PAGE_SIZE_MAX + 1})).status_code == 422


async def test_the_list_holds_what_the_person_may_see(client, login, db) -> None:
    login("u1", "ada")
    await create(client, "open")
    await create(client, "closed", visibility="private")
    await create(client, "shared", visibility="private")
    await share(db, "ada/shared", "u2", "reader")

    def names(page: httpx2.Response) -> set[str]:
        return {item["name"] for item in page.json()["items"]}

    assert names(await client.get(MODELS)) == {"open", "closed", "shared"}
    login("u2", "bob")
    assert names(await client.get(MODELS)) == {"open", "shared"}
    login("u3", "eve")
    assert names(await client.get(MODELS)) == {"open"}
    login("u9", "root", admin=True)
    assert names(await client.get(MODELS)) == {"open", "closed", "shared"}


async def test_the_list_is_filtered(client, login) -> None:
    login("u1", "ada")
    await create(
        client,
        "a",
        tasks=["ner"],
        inputs=["text"],
        library="Transformers",
        languages=["fr"],
        license="mit",
        tags=["x", "y"],
    )
    await create(
        client,
        "b",
        tasks=["image_detection"],
        inputs=["image"],
        library="pytorch",
        languages=["en"],
        license="apache-2.0",
        tags=["x"],
    )
    login("u2", "bob")
    await create(client, "c", description="Reads receipts", tasks=["ner", "qa"], inputs=["text", "image"], tags=["z"])

    async def names(**params) -> list[str]:
        page = (await client.get(MODELS, params={"sort": "updated", **params})).json()
        return sorted(item["name"] for item in page["items"])

    assert await names(owner="ada") == ["a", "b"]
    assert await names(task="ner") == ["a", "c"]
    assert await names(task="qa") == ["c"]
    assert await names(modality="image") == ["b", "c"]
    assert await names(library="transformers") == ["a"]
    assert await names(language="en") == ["b"]
    assert await names(license="MIT") == ["a"]
    assert await names(tags=["x"]) == ["a", "b"]
    assert await names(tags=["x", "y"]) == ["a"]  # all of them
    assert await names(q="receipts") == ["c"]
    assert await names(q="ada/b") == ["b"]
    assert await names(q="Z") == ["c"]  # the tags, whatever the case
    assert await names(task="ner", modality="image") == ["c"]
    assert await names(task="nothing") == []


async def test_a_search_takes_percent_and_underscore_literally(client, login) -> None:
    login()
    await create(client, "a_b")
    await create(client, "axb")
    page = (await client.get(MODELS, params={"q": "a_b"})).json()
    assert [item["name"] for item in page["items"]] == ["a_b"]
    assert (await client.get(MODELS, params={"q": "%"})).json()["total"] == 0


async def test_the_list_is_sorted(client, login) -> None:
    login("u1", "ada")
    await create(client, "first")
    await create(client, "second")
    login("u2", "bob")
    await client.put(f"{MODELS}/ada/first/like")
    page = (await client.get(MODELS, params={"sort": "likes"})).json()
    assert [(item["name"], item["likes"], item["liked"]) for item in page["items"]] == [
        ("first", 1, True),
        ("second", 0, False),
    ]
    page = (await client.get(MODELS, params={"sort": "updated"})).json()
    assert page["items"][0]["name"] == "second"
    assert (await client.get(MODELS, params={"sort": "random"})).status_code == 422


# ---- the link to MLflow


@pytest.fixture
def public_mlflow(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "MLFLOW_PUBLIC_URL", "https://mlflow.example.org")
    monkeypatch.setattr(settings, "MLFLOW_TRACKING_URI", "http://mlflow:5000")
    return "https://mlflow.example.org"


async def test_the_people_who_can_edit_get_the_link_to_mlflow(client, login, db, public_mlflow) -> None:
    login("u1", "ada")
    await create(client)
    await register(db, "ada/sentiment-fr")
    await share(db, "ada/sentiment-fr", "u2", "maintainer")
    expected = f"{public_mlflow}/#/models/ada~sentiment-fr"
    login("u1", "ada")
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).json()["mlflow_url"] == expected
    login("u2", "bob")
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).json()["mlflow_url"] == expected
    login("u9", "root", admin=True)
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).json()["mlflow_url"] == expected


async def test_the_other_people_do_not_get_the_link_at_all(client, login, db, public_mlflow) -> None:
    login("u1", "ada")
    await create(client)
    await register(db, "ada/sentiment-fr")
    await share(db, "ada/sentiment-fr", "u2", "reader")
    for user_id in ("u2", "u3"):  # a reader, a stranger
        login(user_id, "someone")
        response = await client.get(f"{MODELS}/ada/sentiment-fr")
        assert "mlflow_url" not in response.json()  # absent, not null
        assert "mlflow" not in response.text.lower().replace("ada~sentiment-fr", "")
        for item in (await client.get(MODELS)).json()["items"]:
            assert "mlflow_url" not in item


async def test_no_link_without_a_public_address_or_before_mlflow_knows_the_model(
    client, login, db, monkeypatch, public_mlflow
) -> None:
    login()
    await create(client)
    assert "mlflow_url" not in (await client.get(f"{MODELS}/ada/sentiment-fr")).json()  # no version in MLflow yet
    await register(db, "ada/sentiment-fr")
    monkeypatch.setattr(settings, "MLFLOW_PUBLIC_URL", "")
    assert "mlflow_url" not in (await client.get(f"{MODELS}/ada/sentiment-fr")).json()


async def test_the_link_never_holds_the_internal_address(client, login, db, public_mlflow) -> None:
    login()
    await create(client)
    await register(db, "ada/sentiment-fr")
    response = await client.get(f"{MODELS}/ada/sentiment-fr")
    assert settings.MLFLOW_TRACKING_URI not in response.text
    assert "mlflow:5000" not in response.text
