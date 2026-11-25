import pytest

from tests.routers.test_datasets import DATASETS, create, share

URL = f"{DATASETS}/ada/movie-reviews/members"


async def test_the_creator_gives_access_changes_the_role_and_takes_it_away(client, login) -> None:
    login("u1", "ada")
    await create(client, visibility="private")
    added = await client.put(f"{URL}/u2", json={"role": "reader"})
    assert added.status_code == 200
    assert (added.json()["user_id"], added.json()["role"], added.json()["added_by"]) == ("u2", "reader", "u1")
    assert (await client.put(f"{URL}/u2", json={"role": "annotator"})).json()["role"] == "annotator"
    assert [(m["user_id"], m["role"]) for m in (await client.get(URL)).json()] == [("u2", "annotator")]
    login("u2", "bob")
    assert (await client.get(f"{DATASETS}/ada/movie-reviews")).status_code == 200
    login("u1", "ada")
    assert (await client.delete(f"{URL}/u2")).status_code == 204
    assert (await client.get(URL)).json() == []
    login("u2", "bob")
    assert (await client.get(f"{DATASETS}/ada/movie-reviews")).status_code == 404  # it is private again


@pytest.mark.parametrize("role", ["reader", "annotator", "maintainer"])
async def test_the_three_roles_exist(client, login, role: str) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.put(f"{URL}/u2", json={"role": role})).json()["role"] == role


async def test_a_maintainer_and_an_admin_manage_the_members(client, login, db) -> None:
    login("u1", "ada")
    await create(client)
    await share(db, "ada/movie-reviews", "u2", "maintainer")
    login("u2", "bob")
    assert (await client.put(f"{URL}/u3", json={"role": "reader"})).status_code == 200
    login("u9", "root", admin=True)
    assert (await client.delete(f"{URL}/u3")).status_code == 204


async def test_a_reader_an_annotator_and_a_stranger_do_not_manage_the_members(client, login, db) -> None:
    login("u1", "ada")
    await create(client)
    await share(db, "ada/movie-reviews", "u2", "reader")
    await share(db, "ada/movie-reviews", "u3", "annotator")
    for user_id in ("u2", "u3", "u4"):
        login(user_id, "someone")
        assert (await client.get(URL)).status_code == 403
        assert (await client.put(f"{URL}/u5", json={"role": "reader"})).status_code == 403
        assert (await client.delete(f"{URL}/u2")).status_code == 403
    login("u1", "ada")
    assert sorted(m["user_id"] for m in (await client.get(URL)).json()) == ["u2", "u3"]  # nothing changed


async def test_a_private_dataset_does_not_say_it_exists_to_a_stranger(client, login) -> None:
    login("u1", "ada")
    await create(client, visibility="private")
    login("u2", "bob")
    assert (await client.get(URL)).status_code == 404
    assert (await client.put(f"{URL}/u3", json={"role": "reader"})).status_code == 404


async def test_nothing_without_a_login(client) -> None:
    assert (await client.get(URL)).status_code == 401


async def test_the_creator_is_not_a_member(client, login) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.put(f"{URL}/u1", json={"role": "reader"})).status_code == 422


@pytest.mark.parametrize("body", [{}, {"role": "owner"}, {"role": "admin"}])
async def test_only_the_three_roles_are_accepted(client, login, body: dict) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.put(f"{URL}/u2", json=body)).status_code == 422


async def test_removing_somebody_who_is_not_a_member(client, login) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.delete(f"{URL}/u2")).status_code == 404


async def test_the_members_go_with_the_dataset(client, login) -> None:
    login("u1", "ada")
    await create(client)
    await client.put(f"{URL}/u2", json={"role": "reader"})
    assert (await client.delete(f"{DATASETS}/ada/movie-reviews")).status_code == 204
    await create(client)  # the same name again: nobody is a member of the new one
    assert (await client.get(URL)).json() == []
