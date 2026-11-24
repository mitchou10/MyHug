import pytest

from tests.routers.test_models import MODELS, create, share

URL = f"{MODELS}/ada/sentiment-fr/members"


async def test_the_creator_gives_access_changes_the_role_and_takes_it_away(client, login) -> None:
    login("u1", "ada")
    await create(client, visibility="private")
    added = await client.put(f"{URL}/u2", json={"role": "reader"})
    assert added.status_code == 200
    assert (added.json()["user_id"], added.json()["role"], added.json()["added_by"]) == ("u2", "reader", "u1")
    assert (await client.put(f"{URL}/u2", json={"role": "maintainer"})).json()["role"] == "maintainer"
    assert [(m["user_id"], m["role"]) for m in (await client.get(URL)).json()] == [("u2", "maintainer")]
    login("u2", "bob")
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).status_code == 200
    login("u1", "ada")
    assert (await client.delete(f"{URL}/u2")).status_code == 204
    assert (await client.get(URL)).json() == []
    login("u2", "bob")
    assert (await client.get(f"{MODELS}/ada/sentiment-fr")).status_code == 404  # it is private again


async def test_a_maintainer_and_an_admin_manage_the_members(client, login, db) -> None:
    login("u1", "ada")
    await create(client)
    await share(db, "ada/sentiment-fr", "u2", "maintainer")
    login("u2", "bob")
    assert (await client.put(f"{URL}/u3", json={"role": "reader"})).status_code == 200
    login("u9", "root", admin=True)
    assert (await client.delete(f"{URL}/u3")).status_code == 204


async def test_a_reader_and_a_stranger_do_not_manage_the_members(client, login, db) -> None:
    login("u1", "ada")
    await create(client)
    await share(db, "ada/sentiment-fr", "u2", "reader")
    for user_id in ("u2", "u3"):
        login(user_id, "someone")
        assert (await client.get(URL)).status_code == 403
        assert (await client.put(f"{URL}/u4", json={"role": "reader"})).status_code == 403
        assert (await client.delete(f"{URL}/u2")).status_code == 403
    login("u1", "ada")
    assert [m["user_id"] for m in (await client.get(URL)).json()] == ["u2"]  # nothing changed


async def test_nothing_without_a_login(client) -> None:
    assert (await client.get(URL)).status_code == 401


async def test_the_creator_is_not_a_member(client, login) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.put(f"{URL}/u1", json={"role": "reader"})).status_code == 422


@pytest.mark.parametrize("body", [{}, {"role": "owner"}, {"role": "admin"}, {"role": "annotator"}])
async def test_only_reader_and_maintainer_exist(client, login, body: dict) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.put(f"{URL}/u2", json=body)).status_code == 422


async def test_removing_somebody_who_is_not_a_member(client, login) -> None:
    login("u1", "ada")
    await create(client)
    assert (await client.delete(f"{URL}/u2")).status_code == 404
