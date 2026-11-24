import json
import uuid
from datetime import timedelta

import httpx2
import pytest
from sqlalchemy import select, update

from app.config import settings
from app.models import ModelFile, ModelUpload, ModelVersion
from app.registry import MlflowLinks
from app.services.factory import build_model_uploads
from tests.conftest import MemoryRegistry, MemoryStore
from tests.routers.test_models import MODELS, create, share

ADDRESS = f"{MODELS}/ada/sentiment-fr"
WEIGHTS = b"w" * 1000
CONFIG = b'{"hidden": 8}'
CODE = {"url": "https://github.com/ada/sentiment", "ref": "main", "entrypoint": "src/predict.py"}


@pytest.fixture(autouse=True)
def _mlflow(registry: MemoryRegistry) -> MemoryRegistry:
    """MLflow, in memory, for every test of this file."""
    return registry


async def announce(client: httpx2.AsyncClient, *files: tuple[str, int], **extra):
    body = {"files": [{"path": path, "size": size} for path, size in files], **extra}
    return await client.post(f"{ADDRESS}/uploads", json=body)


async def send_parts(client: httpx2.AsyncClient, store: MemoryStore, upload: dict, contents: dict[str, bytes]) -> None:
    """What the browser does: asks for the addresses of the parts, cuts each file, sends each part to its address."""
    for file in upload["files"]:
        if file.get("already_stored"):
            continue
        data = contents[file["path"]]
        numbers = list(range(1, file["parts_count"] + 1))
        response = await client.post(
            f"/api/model-uploads/{upload['id']}/parts", json={"file_id": file["id"], "numbers": numbers}
        )
        assert response.status_code == 200, response.text
        for part in response.json()["parts"]:
            start = (part["number"] - 1) * file["part_size"]
            store.receive(part["url"], data[start : start + file["part_size"]])


async def push(client: httpx2.AsyncClient, store: MemoryStore, *, code: dict | None = None, **contents: bytes) -> dict:
    """Sends files as a new version and returns it (the calls must succeed)."""
    extra = {"code": code} if code else {}
    contents = {path.replace("__", "/"): data for path, data in contents.items()}  # `a__b` is the path `a/b`
    response = await announce(client, *((path, len(data)) for path, data in contents.items()), **extra)
    assert response.status_code == 201, response.text
    upload = response.json()
    await send_parts(client, store, upload, contents)
    done = await client.post(f"/api/model-uploads/{upload['id']}/complete")
    assert done.status_code == 200, done.text
    return done.json()


async def start(client: httpx2.AsyncClient, login, **fields) -> None:
    login("u1", "ada")
    await create(client, **fields)


# ---- a version with files


async def test_files_make_a_version_registered_in_mlflow(client, login, store, registry: MemoryRegistry, db) -> None:
    await start(client, login)
    version = await push(client, store, **{"weights.bin": WEIGHTS, "config.json": CONFIG})
    assert (version["number"], version["size_bytes"], version["status"], version["code"]) == (
        1,
        len(WEIGHTS) + len(CONFIG),
        "pending",  # a worker reads what was sent in parts
        None,
    )
    assert "ada~sentiment-fr" in registry.models
    assert registry.versions[("ada~sentiment-fr", "1")].run_id
    run_id = registry.versions[("ada~sentiment-fr", "1")].run_id
    assert run_id is not None
    manifest = json.loads(registry.logged[f"{run_id}/MANIFEST.json"])
    assert [f["path"] for f in manifest["files"]] == ["config.json", "weights.bin"]
    assert registry.runs[run_id]["status"] == "FINISHED"
    stored = (await db.execute(select(ModelVersion))).scalar_one()
    assert (stored.mlflow_name, stored.mlflow_version, stored.mlflow_run_id) == ("ada~sentiment-fr", "1", run_id)
    model = (await client.get(ADDRESS)).json()
    assert (model["version"], model["size_bytes"]) == (1, len(WEIGHTS) + len(CONFIG))


async def test_the_second_version_keeps_the_files_it_does_not_change_and_stores_them_once(
    client, login, store, db
) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS, "config.json": CONFIG})
    second = await push(client, store, **{"config.json": b'{"hidden": 16}'})
    assert second["number"] == 2
    files = {f["path"]: f for f in (await client.get(f"{ADDRESS}/files")).json()}
    assert sorted(files) == ["config.json", "weights.bin"]
    keys = {(f.version_id, f.path): f.storage_key for f in (await db.execute(select(ModelFile))).scalars()}
    versions = {v.number: v.id for v in (await db.execute(select(ModelVersion))).scalars()}
    assert keys[(versions[1], "weights.bin")] == keys[(versions[2], "weights.bin")]  # the same object
    assert keys[(versions[1], "config.json")] != keys[(versions[2], "config.json")]
    assert len({k for k in store.objects if k.startswith("models/")}) == 3  # weights once, two configs


async def test_a_file_the_model_holds_is_not_sent_again(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    # a worker has read it: its fingerprint is known
    await db.execute(update(ModelFile).values(sha256="a" * 64))
    await db.commit()
    response = await client.post(
        f"{ADDRESS}/uploads", json={"files": [{"path": "copy.bin", "size": len(WEIGHTS), "sha256": "a" * 64}]}
    )
    upload = response.json()
    assert upload["files"][0]["already_stored"] is True
    done = await client.post(f"/api/model-uploads/{upload['id']}/complete")
    assert done.status_code == 200
    keys = {f.path: f.storage_key for f in (await db.execute(select(ModelFile))).scalars() if f.path.endswith(".bin")}
    assert keys["copy.bin"] == keys["weights.bin"]


async def test_what_the_browser_announces_is_not_believed(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})  # sent in parts: no fingerprint of its own
    response = await client.post(
        f"{ADDRESS}/uploads", json={"files": [{"path": "other.bin", "size": len(WEIGHTS), "sha256": "b" * 64}]}
    )
    assert response.json()["files"][0]["already_stored"] is False


async def test_a_file_can_be_taken_out_in_a_new_version(client, login, store) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS, "config.json": CONFIG})
    response = await announce(client, ("extra.txt", 5), remove=["config.json"])
    upload = response.json()
    await send_parts(client, store, upload, {"extra.txt": b"extra"})
    assert (await client.post(f"/api/model-uploads/{upload['id']}/complete")).status_code == 200
    assert sorted(f["path"] for f in (await client.get(f"{ADDRESS}/files")).json()) == ["extra.txt", "weights.bin"]
    assert (await announce(client, ("x", 1), remove=["nothing.bin"])).status_code == 404


async def test_completing_twice_gives_the_same_version(client, login, store, registry) -> None:
    await start(client, login)
    response = await announce(client, ("weights.bin", len(WEIGHTS)))
    upload = response.json()
    await send_parts(client, store, upload, {"weights.bin": WEIGHTS})
    first = await client.post(f"/api/model-uploads/{upload['id']}/complete")
    second = await client.post(f"/api/model-uploads/{upload['id']}/complete")
    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["number"] == second.json()["number"] == 1
    assert len((await client.get(f"{ADDRESS}/versions")).json()) == 1
    assert len(registry.versions) == 1


async def test_a_part_that_did_not_arrive_is_told(client, login, store) -> None:
    await start(client, login)
    upload = (await announce(client, ("weights.bin", len(WEIGHTS)))).json()
    done = await client.post(f"/api/model-uploads/{upload['id']}/complete")
    assert done.status_code == 422
    assert "weights.bin" in done.json()["detail"]
    send = await client.post(
        f"/api/model-uploads/{upload['id']}/parts", json={"file_id": upload["files"][0]["id"], "numbers": [2]}
    )
    assert send.status_code == 422


# ---- nothing is left behind


async def test_nothing_is_left_when_mlflow_is_down_at_the_end(client, login, store, registry, db) -> None:
    await start(client, login)
    upload = (await announce(client, ("weights.bin", len(WEIGHTS)), code=CODE)).json()
    await send_parts(client, store, upload, {"weights.bin": WEIGHTS})
    registry.down = True
    assert (await client.post(f"/api/model-uploads/{upload['id']}/complete")).status_code == 503
    registry.down = False
    assert (await db.execute(select(ModelVersion))).first() is None
    assert not [k for k in store.objects if k.startswith("models/")]  # the joined object is gone
    assert (
        not store.uploads or all(not u["open"] for u in store.uploads.values()) if hasattr(store, "uploads") else True
    )
    assert registry.models == set() and registry.versions == {}
    assert (await client.get(f"/api/model-uploads/{upload['id']}")).json()["status"] == "aborted"


async def test_what_mlflow_made_is_taken_back_when_the_database_fails(
    client, login, store, registry, monkeypatch
) -> None:
    await start(client, login)
    upload = (await announce(client, ("weights.bin", len(WEIGHTS)))).json()
    await send_parts(client, store, upload, {"weights.bin": WEIGHTS})

    async def broken(self) -> None:
        raise RuntimeError("the database is gone")

    from app.repositories.model_versions import ModelVersionRepository

    monkeypatch.setattr(ModelVersionRepository, "commit", broken)
    with pytest.raises(RuntimeError):
        await client.post(f"/api/model-uploads/{upload['id']}/complete")
    assert registry.versions == {} and registry.models == set()
    assert "delete_version" in registry.calls and "delete_model" in registry.calls


async def test_a_registered_model_that_had_versions_is_not_deleted_when_a_new_one_fails(
    client, login, store, registry, monkeypatch
) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    upload = (await announce(client, ("more.bin", 3))).json()
    await send_parts(client, store, upload, {"more.bin": b"abc"})
    registry.fail_on = "create_version"
    assert (await client.post(f"/api/model-uploads/{upload['id']}/complete")).status_code == 503
    assert "ada~sentiment-fr" in registry.models and len(registry.versions) == 1


# ---- code


async def test_a_version_can_be_only_code(client, login, registry) -> None:
    await start(client, login)
    response = await client.post(f"{ADDRESS}/versions", json={"code": CODE, "message": "just code"})
    assert response.status_code == 201, response.text
    version = response.json()
    assert version["number"] == 1 and version["status"] == "ready"
    assert version["code"] == {
        "url": "https://github.com/ada/sentiment",
        "ref": "main",
        "ref_kind": "unknown",
        "path": None,
        "entrypoint": "src/predict.py",
        "sha": None,
        "state": "unresolved",
        "error": None,
        "tree_url": None,  # nothing to link to until it is pinned
    }
    assert registry.models == set()  # MLflow knows nothing of a version without artifacts
    assert (await client.get(f"{ADDRESS}/files")).json() == []


async def test_a_version_can_be_files_and_code(client, login, store) -> None:
    await start(client, login)
    version = await push(client, store, code=CODE, **{"weights.bin": WEIGHTS})
    assert version["code"]["url"] == CODE["url"] and version["code"]["state"] == "unresolved"
    detail = (await client.get(f"{ADDRESS}/versions/1")).json()
    assert [f["path"] for f in detail["files"]] == ["weights.bin"]


async def test_a_version_with_neither_is_refused(client, login) -> None:
    await start(client, login)
    assert (await client.post(f"{ADDRESS}/versions", json={"message": "nothing"})).status_code == 422
    assert (await announce(client)).status_code == 422
    assert (await client.get(f"{ADDRESS}/versions")).json() == []


async def test_a_commit_is_recognised_and_the_code_is_not_inherited(client, login, store) -> None:
    await start(client, login)
    sha = "a" * 40
    version = (await client.post(f"{ADDRESS}/versions", json={"code": {**CODE, "ref": sha}})).json()
    assert version["code"]["ref_kind"] == "commit"
    second = await push(client, store, **{"weights.bin": WEIGHTS})
    assert second["code"] is None  # a version says its own code
    assert (await client.get(f"{ADDRESS}/versions/1")).json()["code"]["ref"] == sha  # and the old one is unchanged


@pytest.mark.parametrize(
    "code",
    [
        {"url": "http://github.com/ada/x"},  # not https
        {"url": "https://user:pw@github.com/ada/x"},  # credentials
        {"url": "https://ada@github.com/ada/x"},
        {"url": "https://127.0.0.1/ada/x"},  # an IP address
        {"url": "https://[::1]/ada/x"},
        {"url": "https://169.254.169.254/latest/meta-data"},
        {"url": "https://github.com:8443/ada/x"},  # an odd port
        {"url": "https://github.com:99999999/ada/x"},
        {"url": "https://evil.example/ada/x"},  # another host
        {"url": "https://github.com.evil.example/ada/x"},
        {"url": "https://notgithub.com/ada/x"},
        {"url": "https://github.com/ada/../x"},  # `..` in the path
        {"url": "https://github.com/ada/x/../../y"},
        {"url": "https://github.com/%2e%2e/x"},
        {"url": "https://github.com/ada"},  # not a repository
        {"url": "https://github.com/ada/x/tree/main"},
        {"url": "https://github.com/ada/x?x=1"},
        {"url": "https://github.com/ada/x#frag"},
        {"url": "https://github.com/ada/x y"},
        {"url": "file:///etc/passwd"},
        {"url": "ssh://git@github.com/ada/x"},
        {"url": "git@github.com:ada/x.git"},
        {"url": ""},
        {"url": "https://github.com/ada/x", "path": "../etc"},
        {"url": "https://github.com/ada/x", "path": "/etc"},
        {"url": "https://github.com/ada/x", "entrypoint": "a/../../b.py"},
        {"url": "https://github.com/ada/x", "ref": "a..b"},
        {"url": "https://github.com/ada/x", "ref": "-rf"},
        {"url": "https://github.com/ada/x", "ref": "not a commit", "ref_kind": "commit"},
        {"url": "https://github.com/ada/x", "ref_kind": "tag"},  # a kind of nothing
        {"url": "https://github.com/ada/x", "ref": "v1", "ref_kind": "weird"},
    ],
)
async def test_a_code_reference_that_breaks_a_rule_is_refused(client, login, code: dict) -> None:
    await start(client, login)
    assert (await client.post(f"{ADDRESS}/versions", json={"code": code})).status_code == 422
    assert (await announce(client, ("w.bin", 3), code=code)).status_code == 422  # the same before an upload starts


@pytest.mark.parametrize(
    "url", ["https://github.com/ada/x", "https://GitHub.com/ada/x.git", "https://gitlab.com/ada/x/"]
)
async def test_a_repository_of_an_allowed_host_is_kept_as_written(client, login, url: str) -> None:
    await start(client, login)
    version = (await client.post(f"{ADDRESS}/versions", json={"code": {"url": url}})).json()
    assert version["code"]["url"] == url


# ---- reading, downloading, deleting


async def test_a_version_is_read_with_its_files(client, login, store) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS, "sub__tokenizer.json": b"{}"})
    versions = (await client.get(f"{ADDRESS}/versions")).json()
    assert [v["number"] for v in versions] == [1]
    detail = (await client.get(f"{ADDRESS}/versions/1")).json()
    assert [(f["path"], f["size_bytes"]) for f in detail["files"]] == [("sub/tokenizer.json", 2), ("weights.bin", 1000)]
    assert (await client.get(f"{ADDRESS}/versions/7")).status_code == 404


async def test_a_file_is_downloaded_through_a_signed_address_and_counted(client, login, store) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    login("u2", "bob")  # a stranger reads a public model
    response = await client.get(f"{ADDRESS}/files/weights.bin", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("memory://get/models/")
    assert (await client.get(ADDRESS)).json()["downloads"] == 1
    assert (await client.get(f"{ADDRESS}/files/nothing.bin")).status_code == 404
    assert (await client.get(f"{ADDRESS}/files/../x", follow_redirects=False)).status_code in (404, 422)


async def test_a_version_that_failed_the_checks_is_not_given(client, login, store, db) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    await db.execute(
        update(ModelVersion).values(status="failed", error="weights.bin: the fingerprint is not the announced one")
    )
    await db.commit()
    assert (await client.get(f"{ADDRESS}/files/weights.bin")).status_code == 409


async def test_a_deleted_version_keeps_the_files_another_version_holds(client, login, store, registry) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS, "config.json": CONFIG})
    await push(client, store, **{"config.json": b"{}"})
    before = {k for k in store.objects if k.startswith("models/")}
    assert len(before) == 3
    assert (await client.delete(f"{ADDRESS}/versions/1")).status_code == 204
    after = {k for k in store.objects if k.startswith("models/")}
    assert len(after) == 2  # the first config went; the weights are still held by version 2
    assert ("ada~sentiment-fr", "1") not in registry.versions
    assert (
        await client.get(f"{ADDRESS}/files/weights.bin", params={"version": 2}, follow_redirects=False)
    ).status_code == 302
    assert (await client.get(f"{ADDRESS}/versions/1")).status_code == 404
    # the model shows what the latest holds
    assert (await client.get(ADDRESS)).json()["version"] == 2
    assert (await client.delete(f"{ADDRESS}/versions/2")).status_code == 204
    model = (await client.get(ADDRESS)).json()
    assert (model["version"], model["size_bytes"]) == (0, 0)
    assert not [k for k in store.objects if k.startswith("models/")]


async def test_a_version_is_not_deleted_while_mlflow_does_not_answer(client, login, store, registry) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    registry.down = True
    assert (await client.delete(f"{ADDRESS}/versions/1")).status_code == 503
    registry.down = False
    assert len((await client.get(f"{ADDRESS}/versions")).json()) == 1
    assert (await client.delete(f"{ADDRESS}/versions/1")).status_code == 204


async def test_a_deleted_model_takes_its_files_with_it(client, login, store, registry) -> None:
    await start(client, login)
    await push(client, store, **{"weights.bin": WEIGHTS})
    assert (await client.delete(ADDRESS)).status_code == 204
    assert not [k for k in store.objects if k.startswith("models/")]
    assert registry.models == set()


# ---- rights


async def test_only_editors_upload_and_everybody_who_can_see_reads(client, login, store, db) -> None:
    await start(client, login, visibility="private")
    await push(client, store, **{"weights.bin": WEIGHTS})
    await share(db, "ada/sentiment-fr", "u2", "reader")
    await share(db, "ada/sentiment-fr", "u3", "maintainer")
    login("u2", "bob")  # a reader
    assert (await client.get(f"{ADDRESS}/versions")).status_code == 200
    assert (await client.get(f"{ADDRESS}/files/weights.bin", follow_redirects=False)).status_code == 302
    assert (await announce(client, ("x.bin", 3))).status_code == 403
    assert (await client.post(f"{ADDRESS}/versions", json={"code": CODE})).status_code == 403
    assert (await client.delete(f"{ADDRESS}/versions/1")).status_code == 403
    login("u3", "carol")  # a maintainer
    assert (await announce(client, ("x.bin", 3))).status_code == 201
    login("u4", "eve")  # a stranger: the private model is not there at all
    for call in (
        client.get(f"{ADDRESS}/versions"),
        client.get(f"{ADDRESS}/versions/1"),
        client.get(f"{ADDRESS}/files"),
        client.get(f"{ADDRESS}/files/weights.bin"),
        announce(client, ("x.bin", 3)),
        client.post(f"{ADDRESS}/versions", json={"code": CODE}),
        client.delete(f"{ADDRESS}/versions/1"),
    ):
        assert (await call).status_code == 404


async def test_somebody_else_cannot_use_an_upload(client, login, store) -> None:
    await start(client, login)
    upload = (await announce(client, ("weights.bin", len(WEIGHTS)))).json()
    login("u2", "bob")
    for call in (
        client.get(f"/api/model-uploads/{upload['id']}"),
        client.post(f"/api/model-uploads/{upload['id']}/complete"),
        client.delete(f"/api/model-uploads/{upload['id']}"),
        client.post(f"/api/model-uploads/{upload['id']}/parts", json={"file_id": str(uuid.uuid4()), "numbers": [1]}),
    ):
        assert (await call).status_code == 404


async def test_the_limits_are_in_the_settings(client, login, monkeypatch) -> None:
    await start(client, login)
    monkeypatch.setattr(settings, "MODEL_FILE_MAX_BYTES", 10)
    assert (await announce(client, ("big.bin", 11))).status_code == 413
    assert (await announce(client, ("empty.bin", 0))).status_code == 422
    monkeypatch.setattr(settings, "MODEL_VERSION_MAX_FILES", 2)
    assert (await announce(client, ("a", 1), ("b", 1), ("c", 1))).status_code == 422
    assert (await announce(client, ("a", 1), ("a", 1))).status_code == 422  # the same path twice


# ---- abandoned uploads


async def test_an_abandoned_upload_is_given_up_and_its_parts_are_freed(client, login, store, db) -> None:
    await start(client, login)
    upload = (await announce(client, ("weights.bin", len(WEIGHTS)))).json()
    await send_parts(client, store, upload, {"weights.bin": WEIGHTS})
    await db.execute(update(ModelUpload).values(expires_at=ModelUpload.created_at - timedelta(hours=1)))
    await db.commit()
    service = build_model_uploads(db, store, MemoryRegistry(), MlflowLinks(""))
    assert await service.expire_stale() == 1
    assert (await client.get(f"/api/model-uploads/{upload['id']}")).json()["status"] == "expired"
    assert (await client.post(f"/api/model-uploads/{upload['id']}/complete")).status_code == 409
    assert not any(u.get("parts") for u in store.uploads.values())


# ---- the link to MLflow on a version


async def test_the_link_to_a_version_is_for_the_editors_only(client, login, store, db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MLFLOW_PUBLIC_URL", "https://mlflow.example.org")
    monkeypatch.setattr(settings, "MLFLOW_TRACKING_URI", "http://mlflow:5000")
    await start(client, login)
    await client.post(f"{ADDRESS}/versions", json={"code": CODE})  # a version MLflow does not know
    await push(client, store, **{"weights.bin": WEIGHTS})
    await share(db, "ada/sentiment-fr", "u2", "reader")
    versions = (await client.get(f"{ADDRESS}/versions")).json()
    by_number = {v["number"]: v for v in versions}
    assert "mlflow_url" not in by_number[1]  # nothing to see there
    assert by_number[2]["mlflow_url"] == "https://mlflow.example.org/#/models/ada~sentiment-fr/versions/1"
    assert "mlflow_url" in (await client.get(f"{ADDRESS}/versions/2")).json()
    login("u2", "bob")
    for call in (client.get(f"{ADDRESS}/versions"), client.get(f"{ADDRESS}/versions/2")):
        text = (await call).text
        assert "mlflow_url" not in text and "mlflow:5000" not in text
