import httpx2
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, DatasetMember

DATASETS = "/api/datasets"


async def create(client: httpx2.AsyncClient, name: str = "movie-reviews", **fields) -> dict:
    """Creates a dataset as the logged-in user and returns it (the call must succeed)."""
    response = await client.post(DATASETS, json={"name": name, "modality": "text", **fields})
    assert response.status_code == 201, response.text
    return response.json()


async def share(db: AsyncSession, address: str, user_id: str, role: str) -> None:
    owner, name = address.split("/")
    dataset = (await db.execute(select(Dataset).where(Dataset.owner == owner, Dataset.name == name))).scalar_one()
    db.add(DatasetMember(dataset_id=dataset.id, user_id=user_id, role=role, added_by="u1"))
    await db.commit()


# ---- creating


async def test_a_dataset_is_created_in_the_name_of_its_creator(client, login) -> None:
    login("u1", "Ada")
    dataset = await create(
        client,
        description=" Reviews. ",
        language="fr",
        license="cc-by-4.0",
        tags=["NLP", " nlp ", "sentiment"],
        card="# Reviews",
    )
    assert (dataset["owner"], dataset["name"], dataset["modality"]) == (
        "ada",
        "movie-reviews",
        "text",
    )  # the owner is lowercase
    assert dataset["description"] == " Reviews. "  # the text is kept as it was sent
    assert dataset["tags"] == ["nlp", "sentiment"]  # lowercase, without duplicates
    assert (dataset["visibility"], dataset["downloads"], dataset["likes"], dataset["liked"]) == ("public", 0, 0, False)
    assert (dataset["created_by"], dataset["created_by_username"], dataset["can_edit"], dataset["card"]) == (
        "u1",
        "Ada",
        True,
        "# Reviews",
    )
    assert dataset["id"] and dataset["created_at"] and dataset["updated_at"]


async def test_the_namespace_is_made_of_what_an_address_allows(client, login) -> None:
    login("u1", "Ada Lovelace!")
    assert (await create(client))["owner"] == "ada-lovelace"


async def test_nothing_is_created_without_a_login(client) -> None:
    assert (await client.post(DATASETS, json={"name": "x", "modality": "text"})).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"modality": "text"},  # no name
        {"name": "x"},  # no modality
        {"name": "Has Capitals", "modality": "text"},
        {"name": "-leading-dash", "modality": "text"},
        {"name": "a/b", "modality": "text"},
        {"name": "x" * 101, "modality": "text"},
        {"name": "x", "modality": "model"},
        {"name": "x", "modality": "text", "visibility": "secret"},
        {"name": "x", "modality": "text", "tags": ["t"] * 21},
        {"name": "x", "modality": "text", "description": "d" * 1001},
    ],
)
async def test_what_is_not_valid_is_refused(client, login, body: dict) -> None:
    login()
    assert (await client.post(DATASETS, json=body)).status_code == 422


async def test_a_person_cannot_have_two_datasets_with_the_same_name(client, login) -> None:
    login("u1", "ada")
    await create(client)
    response = await client.post(DATASETS, json={"name": "movie-reviews", "modality": "image"})
    assert response.status_code == 409
    login("u2", "grace")
    assert (await create(client))["owner"] == "grace"  # somebody else can use the name


# ---- reading


async def test_a_dataset_is_read_at_its_address(client, login) -> None:
    login("u1", "ada")
    created = await create(client)
    response = await client.get(f"{DATASETS}/ada/movie-reviews")
    assert response.status_code == 200 and response.json() == created


async def test_the_address_does_not_care_about_the_case(client, login) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.get(f"{DATASETS}/Ada/Movie-Reviews")).status_code == 200


async def test_an_unknown_dataset_is_not_found(client, login) -> None:
    login()
    assert (await client.get(f"{DATASETS}/ada/nothing")).status_code == 404


async def test_somebody_else_can_read_a_public_dataset_but_not_change_it(client, login) -> None:
    login("u1", "ada")
    await create(client)
    login("u2", "grace")
    dataset = (await client.get(f"{DATASETS}/ada/movie-reviews")).json()
    assert dataset["can_edit"] is False


async def test_a_private_dataset_does_not_exist_for_those_who_have_no_access(client, login, db) -> None:
    login("u1", "ada")
    await create(client, visibility="private")
    login("u2", "grace")
    assert (await client.get(f"{DATASETS}/ada/movie-reviews")).status_code == 404
    assert (await client.patch(f"{DATASETS}/ada/movie-reviews", json={"card": "x"})).status_code == 404
    assert (await client.delete(f"{DATASETS}/ada/movie-reviews")).status_code == 404
    assert (await client.put(f"{DATASETS}/ada/movie-reviews/like")).status_code == 404
    await share(db, "ada/movie-reviews", "u2", "reader")
    assert (await client.get(f"{DATASETS}/ada/movie-reviews")).status_code == 200  # given access
    login("a1", "root", admin=True)
    assert (await client.get(f"{DATASETS}/ada/movie-reviews")).status_code == 200  # the admin sees all


# ---- listing


async def test_the_list_shows_what_the_person_may_see(client, login, db) -> None:
    login("u1", "ada")
    await create(client, "public-one")
    await create(client, "private-one", visibility="private")
    await create(client, "shared-one", visibility="private")
    login("u2", "grace")
    await create(client, "mine")
    await share(db, "ada/shared-one", "u2", "reader")
    names = {d["name"] for d in (await client.get(DATASETS)).json()["items"]}
    assert names == {"public-one", "shared-one", "mine"}  # not private-one
    login("a1", "root", admin=True)
    assert (await client.get(DATASETS)).json()["total"] == 4


async def test_the_list_is_filtered_by_modality(client, login) -> None:
    login()
    await create(client, "texts")
    await create(client, "pictures", modality="image")
    page = (await client.get(DATASETS, params={"modality": "image"})).json()
    assert [d["name"] for d in page["items"]] == ["pictures"] and page["total"] == 1
    assert (await client.get(DATASETS, params={"modality": "model"})).status_code == 422


async def test_the_list_is_searched_in_the_address_the_description_and_the_tags(client, login) -> None:
    login("u1", "ada")
    await create(client, "reviews", description="Films seen at the cinema")
    await create(client, "birds", tags=["audio", "biodiversity"])
    await create(client, "prices")

    async def found(q: str) -> list[str]:
        return sorted(d["name"] for d in (await client.get(DATASETS, params={"q": q})).json()["items"])

    assert await found("CINEMA") == ["reviews"]  # the description, whatever the case
    assert await found("biodiv") == ["birds"]  # a tag
    assert await found("ada/pri") == ["prices"]  # the address
    assert await found("%") == []  # a percent sign is not a wildcard
    assert await found("zzz") == []


async def test_the_list_is_sorted_and_paged(client, login) -> None:
    login("u1", "ada")
    for name in ("a", "b", "c"):
        await create(client, name)
    login("u2", "grace")
    await client.put(f"{DATASETS}/ada/b/like")
    first = (await client.get(DATASETS, params={"sort": "likes", "limit": 2})).json()
    assert [d["name"] for d in first["items"]][0] == "b"  # the one that is liked
    assert (first["total"], first["limit"], first["offset"]) == (3, 2, 0)
    second = (await client.get(DATASETS, params={"sort": "likes", "limit": 2, "offset": 2})).json()
    assert len(second["items"]) == 1
    assert (await client.get(DATASETS, params={"sort": "name"})).status_code == 422
    assert (await client.get(DATASETS, params={"limit": 0})).status_code == 422


async def test_the_list_says_which_datasets_i_like(client, login) -> None:
    login("u1", "ada")
    await create(client, "a")
    await create(client, "b")
    await client.put(f"{DATASETS}/ada/a/like")
    liked = {d["name"]: d["liked"] for d in (await client.get(DATASETS)).json()["items"]}
    assert liked == {"a": True, "b": False}


# ---- changing and deleting


async def test_the_creator_changes_a_dataset(client, login) -> None:
    login("u1", "ada")
    created = await create(client, description="old")
    response = await client.patch(
        f"{DATASETS}/ada/movie-reviews", json={"description": "", "tags": ["x"], "visibility": "private"}
    )
    assert response.status_code == 200
    changed = response.json()
    assert (changed["description"], changed["tags"], changed["visibility"]) == (
        "",
        ["x"],
        "private",
    )  # an empty text is a change
    assert changed["name"] == "movie-reviews" and changed["modality"] == "text"  # the rest stays
    assert changed["updated_at"] > created["updated_at"]


@pytest.mark.parametrize(
    "body", [{}, {"name": "other"}, {"modality": "image"}, {"description": None}, {"visibility": "secret"}]
)
async def test_a_change_must_make_sense(client, login, body: dict) -> None:
    login()
    await create(client)
    assert (await client.patch(f"{DATASETS}/ada/movie-reviews", json=body)).status_code == 422


async def test_only_creators_maintainers_and_admins_change_a_dataset(client, login, db) -> None:
    login("u1", "ada")
    await create(client)
    login("u2", "grace")
    assert (await client.patch(f"{DATASETS}/ada/movie-reviews", json={"card": "x"})).status_code == 403  # may read only
    await share(db, "ada/movie-reviews", "u2", "annotator")
    assert (
        await client.patch(f"{DATASETS}/ada/movie-reviews", json={"card": "x"})
    ).status_code == 403  # may annotate only
    await db.execute(update(DatasetMember).where(DatasetMember.user_id == "u2").values(role="maintainer"))
    await db.commit()
    assert (await client.patch(f"{DATASETS}/ada/movie-reviews", json={"card": "x"})).status_code == 200
    login("a1", "root", admin=True)
    assert (await client.patch(f"{DATASETS}/ada/movie-reviews", json={"card": "y"})).status_code == 200


async def test_a_dataset_is_deleted_by_those_who_may_change_it(client, login) -> None:
    login("u1", "ada")
    await create(client)
    login("u2", "grace")
    assert (await client.delete(f"{DATASETS}/ada/movie-reviews")).status_code == 403
    login("u1", "ada")
    assert (await client.delete(f"{DATASETS}/ada/movie-reviews")).status_code == 204
    assert (await client.get(f"{DATASETS}/ada/movie-reviews")).status_code == 404
    assert (await client.delete(f"{DATASETS}/ada/movie-reviews")).status_code == 404
    assert (await create(client))["name"] == "movie-reviews"  # the name is free again


# ---- liking


async def test_liking_counts_once_per_person(client, login) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.put(f"{DATASETS}/ada/movie-reviews/like")).json() == {"liked": True, "likes": 1}
    assert (await client.put(f"{DATASETS}/ada/movie-reviews/like")).json() == {
        "liked": True,
        "likes": 1,
    }  # again: nothing
    login("u2", "grace")
    assert (await client.put(f"{DATASETS}/ada/movie-reviews/like")).json() == {"liked": True, "likes": 2}
    dataset = (await client.get(f"{DATASETS}/ada/movie-reviews")).json()
    assert (dataset["likes"], dataset["liked"]) == (2, True)


async def test_unliking_takes_the_like_back(client, login) -> None:
    login("u1", "ada")
    await create(client)
    await client.put(f"{DATASETS}/ada/movie-reviews/like")
    assert (await client.delete(f"{DATASETS}/ada/movie-reviews/like")).json() == {"liked": False, "likes": 0}
    assert (await client.delete(f"{DATASETS}/ada/movie-reviews/like")).json() == {
        "liked": False,
        "likes": 0,
    }  # again: nothing
    assert (await client.get(f"{DATASETS}/ada/movie-reviews")).json()["liked"] is False
