from tests.routers.test_datasets import DATASETS


async def test_a_wrong_request_says_what_and_where_but_does_not_echo_what_was_sent(client, login) -> None:
    login("u1", "ada")
    secret = "a-value-that-must-not-come-back"
    response = await client.post(DATASETS, json={"name": "x" * 500, "modality": secret})
    assert response.status_code == 422
    assert secret not in response.text and "x" * 500 not in response.text
    problems = response.json()["detail"]
    assert {tuple(p["loc"]) for p in problems} >= {("body", "modality")}
    assert all(set(p) == {"type", "loc", "msg"} for p in problems)


async def test_a_value_that_is_not_json_is_a_422_not_a_server_error(client, login) -> None:
    login("u1", "ada")
    raw = '{"name": "x", "modality": "text", "tags": [NaN]}'
    response = await client.post(DATASETS, content=raw, headers={"content-type": "application/json"})
    assert response.status_code == 422
