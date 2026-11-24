import json

import httpx2
import pytest

from app.registry import MlflowRegistry, NoRegistry, RegistryRun, registered_name, split_registered_name
from app.services.errors import RegistryConflict, RegistryNotFound, RegistryRejected, RegistryUnavailable

BASE = "http://mlflow:5000"
RUN = RegistryRun(experiment_id="3", run_id="r" * 32, artifact_uri=f"mlflow-artifacts:/3/{'r' * 32}/artifacts")


class Server:
    """A MLflow that answers what it is told to, and remembers what it was asked."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.answers: list[httpx2.Response | Exception] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else httpx2.Response(200, json={})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def say(self, *answers: httpx2.Response | Exception) -> "Server":
        self.answers.extend(answers)
        return self

    @property
    def last(self) -> httpx2.Request:
        return self.requests[-1]

    def body(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content)


def ok(**body) -> httpx2.Response:
    return httpx2.Response(200, json=body)


def error(status: int, code: str, message: str = "nope") -> httpx2.Response:
    return httpx2.Response(status, json={"error_code": code, "message": message})


def registry(server: Server, **options) -> MlflowRegistry:
    return MlflowRegistry(BASE, transport=httpx2.MockTransport(server), **options)


VERSION = {
    "name": "ada~m",
    "version": "2",
    "run_id": "r" * 32,
    "source": RUN.artifact_uri + "/model",
    "status": "READY",
}


# ---- the names


def test_a_model_is_named_in_mlflow_by_its_owner_and_its_name() -> None:
    assert registered_name("ada", "sentiment-fr") == "ada~sentiment-fr"
    assert split_registered_name("ada~sentiment-fr") == ("ada", "sentiment-fr")


@pytest.mark.parametrize("value", ["ada", "~x", "ada~", "a~b~c", ""])
def test_a_name_that_the_platform_did_not_make_cannot_be_taken_apart(value: str) -> None:
    with pytest.raises(ValueError):
        split_registered_name(value)


def test_the_name_has_no_character_mlflow_refuses_and_no_owner_or_name_can_hold_the_separator() -> None:
    from app.schemas.dataset import Slug  # the same slug as everywhere: lowercase, digits, `.`, `_` and `-`

    for owner, name in (("a.b", "c_d"), ("a-b", "c.d"), ("a_b", "c-d")):
        value = registered_name(owner, name)
        assert "/" not in value and ":" not in value and split_registered_name(value) == (owner, name)
    assert Slug is not None


# ---- registered models


async def test_a_registered_model_is_made_by_its_name() -> None:
    server = Server().say(ok(registered_model={"name": "ada~m"}))
    await registry(server).create_model("ada~m")
    assert (server.last.method, server.last.url.path, server.body()) == (
        "POST",
        "/api/2.0/mlflow/registered-models/create",
        {"name": "ada~m"},
    )


async def test_a_name_that_is_taken_is_a_conflict() -> None:
    with pytest.raises(RegistryConflict):
        await registry(Server().say(error(400, "RESOURCE_ALREADY_EXISTS"))).create_model("ada~m")


async def test_a_name_that_mlflow_refuses_is_rejected_with_what_it_says() -> None:
    server = Server().say(error(400, "INVALID_PARAMETER_VALUE", "Names cannot contain '/' or ':'."))
    with pytest.raises(RegistryRejected, match="cannot contain"):
        await registry(server).create_model("ada/m")


async def test_the_existence_of_a_model_is_asked_and_a_missing_one_is_not_an_error() -> None:
    server = Server().say(ok(registered_model={"name": "ada~m"}), error(404, "RESOURCE_DOES_NOT_EXIST"))
    assert await registry(server).model_exists("ada~m") is True
    assert await registry(server).model_exists("ada~x") is False
    assert (server.requests[0].method, dict(server.requests[0].url.params)) == ("GET", {"name": "ada~m"})


async def test_deleting_a_model_that_is_gone_is_fine() -> None:
    server = Server().say(ok(), error(404, "RESOURCE_DOES_NOT_EXIST"))
    await registry(server).delete_model("ada~m")
    await registry(server).delete_model("ada~m")
    assert (server.requests[0].method, server.requests[0].url.path) == (
        "DELETE",
        "/api/2.0/mlflow/registered-models/delete",
    )


# ---- runs


async def test_the_run_of_a_model_is_made_in_its_experiment() -> None:
    server = Server().say(
        ok(experiment={"experiment_id": "3", "lifecycle_stage": "active"}),
        ok(run={"info": {"run_id": "r" * 32, "experiment_id": "3", "artifact_uri": RUN.artifact_uri}}),
    )
    run = await registry(server).create_run("ada~m")
    assert run == RUN
    assert dict(server.requests[0].url.params) == {"experiment_name": "ada~m"}
    assert server.body()["experiment_id"] == "3" and isinstance(server.body()["start_time"], int)


async def test_the_experiment_of_a_model_is_made_the_first_time() -> None:
    server = Server().say(
        error(404, "RESOURCE_DOES_NOT_EXIST"),
        ok(experiment_id="4"),
        ok(run={"info": {"run_id": "x", "experiment_id": "4", "artifact_uri": "mlflow-artifacts:/4/x/artifacts"}}),
    )
    assert (await registry(server).create_run("ada~m")).experiment_id == "4"
    assert server.requests[1].url.path.endswith("/experiments/create") and server.body(1) == {"name": "ada~m"}


async def test_an_experiment_made_by_another_request_in_between_is_used() -> None:
    server = Server().say(
        error(404, "RESOURCE_DOES_NOT_EXIST"),
        error(400, "RESOURCE_ALREADY_EXISTS"),
        ok(experiment={"experiment_id": "5", "lifecycle_stage": "active"}),
        ok(run={"info": {"run_id": "x", "experiment_id": "5", "artifact_uri": "mlflow-artifacts:/5/x/artifacts"}}),
    )
    assert (await registry(server).create_run("ada~m")).experiment_id == "5"


async def test_the_experiment_of_a_deleted_run_family_is_brought_back() -> None:
    server = Server().say(
        ok(experiment={"experiment_id": "3", "lifecycle_stage": "deleted"}),
        ok(),
        ok(run={"info": {"run_id": "x", "experiment_id": "3", "artifact_uri": "mlflow-artifacts:/3/x/artifacts"}}),
    )
    await registry(server).create_run("ada~m")
    assert server.requests[1].url.path.endswith("/experiments/restore") and server.body(1) == {"experiment_id": "3"}


async def test_a_run_is_finished_or_failed_and_deleted() -> None:
    server = Server().say(ok(), ok(), ok(), error(404, "RESOURCE_DOES_NOT_EXIST"))
    reg = registry(server)
    await reg.finish_run("run1")
    await reg.finish_run("run2", failed=True)
    assert [server.body(0)["status"], server.body(1)["status"]] == ["FINISHED", "FAILED"]
    await reg.delete_run("run1")
    await reg.delete_run("run1")  # already gone


# ---- versions


async def test_a_version_is_registered_from_the_artifacts_of_a_run() -> None:
    server = Server().say(ok(model_version=VERSION))
    version = await registry(server).create_version("ada~m", RUN, "model")
    assert (version.name, version.version, version.run_id, version.status) == ("ada~m", "2", "r" * 32, "READY")
    assert server.body() == {"name": "ada~m", "source": RUN.artifact_uri + "/model", "run_id": RUN.run_id}


async def test_a_version_of_the_whole_run_has_the_run_as_its_source() -> None:
    server = Server().say(ok(model_version={**VERSION, "source": RUN.artifact_uri}))
    await registry(server).create_version("ada~m", RUN)
    assert server.body()["source"] == RUN.artifact_uri
    server.say(ok(model_version=VERSION))
    await registry(server).create_version("ada~m", RUN, "/model/")  # slashes at the ends do not matter
    assert server.body()["source"] == RUN.artifact_uri + "/model"


async def test_a_version_of_a_model_that_is_not_there_is_not_found() -> None:
    with pytest.raises(RegistryNotFound):
        await registry(Server().say(error(404, "RESOURCE_DOES_NOT_EXIST"))).create_version("ada~m", RUN)


async def test_a_version_is_read_and_deleted() -> None:
    server = Server().say(ok(model_version=VERSION), error(404, "RESOURCE_DOES_NOT_EXIST"), ok(), error(404, "x"))
    reg = registry(server)
    assert (await reg.get_version("ada~m", "2")).source.endswith("/model")
    assert dict(server.requests[0].url.params) == {"name": "ada~m", "version": "2"}
    with pytest.raises(RegistryNotFound):
        await reg.get_version("ada~m", "9")
    await reg.delete_version("ada~m", "2")
    await reg.delete_version("ada~m", "2")  # already gone


async def test_an_alias_is_set_and_deleted() -> None:
    server = Server().say(ok(), ok())
    reg = registry(server)
    await reg.set_alias("ada~m", "production", "2")
    assert (server.last.method, server.body()) == ("POST", {"name": "ada~m", "alias": "production", "version": "2"})
    await reg.delete_alias("ada~m", "production")
    assert (server.last.method, server.body()) == ("DELETE", {"name": "ada~m", "alias": "production"})


async def test_an_alias_on_a_version_that_is_not_there_is_not_found() -> None:
    with pytest.raises(RegistryNotFound):
        await registry(Server().say(error(404, "RESOURCE_DOES_NOT_EXIST"))).set_alias("ada~m", "production", "9")


# ---- artifacts


def uri(path: str = "model") -> httpx2.Response:
    return ok(artifact_uri=f"mlflow-artifacts:/3/{'r' * 32}/artifacts/{path}".rstrip("/"))


async def test_the_artifacts_of_a_version_are_listed_one_folder_at_a_time() -> None:
    server = Server().say(
        uri(),
        ok(files=[{"path": "MLmodel", "is_dir": False, "file_size": 11}, {"path": "sub", "is_dir": True}]),
        uri(),
        ok(files=[{"path": "w.bin", "is_dir": False, "file_size": 5}]),
    )
    reg = registry(server)
    top = await reg.list_artifacts("ada~m", "2")
    assert [(a.path, a.is_dir, a.size) for a in top] == [("MLmodel", False, 11), ("sub", True, None)]
    assert dict(server.requests[1].url.params) == {"path": f"3/{'r' * 32}/artifacts/model"}
    inside = await reg.list_artifacts("ada~m", "2", "sub")
    assert [(a.path, a.is_dir, a.size) for a in inside] == [("sub/w.bin", False, 5)]  # from the root of the version
    assert dict(server.requests[3].url.params) == {"path": f"3/{'r' * 32}/artifacts/model/sub"}


async def test_an_empty_folder_lists_nothing() -> None:
    assert await registry(Server().say(uri(), ok())).list_artifacts("ada~m", "2") == []


async def test_the_artifacts_have_a_key_in_the_storage_under_the_prefix_of_mlflow() -> None:
    assert (
        await registry(Server().say(uri())).artifact_key_prefix("ada~m", "2") == f"mlflow/3/{'r' * 32}/artifacts/model/"
    )
    other = registry(Server().say(uri()), artifacts_prefix="/store/ml/")
    assert await other.artifact_key_prefix("ada~m", "2") == f"store/ml/3/{'r' * 32}/artifacts/model/"
    bare = registry(Server().say(uri()), artifacts_prefix="")
    assert await bare.artifact_key_prefix("ada~m", "2") == f"3/{'r' * 32}/artifacts/model/"


async def test_artifacts_that_mlflow_does_not_keep_itself_cannot_be_listed() -> None:
    elsewhere = ok(artifact_uri="s3://another-bucket/model")
    with pytest.raises(RegistryRejected):
        await registry(Server().say(elsewhere)).list_artifacts("ada~m", "2")
    with pytest.raises(RegistryRejected):
        await registry(Server().say(elsewhere)).artifact_key_prefix("ada~m", "2")


# ---- what goes wrong


@pytest.mark.parametrize(
    "answer",
    [
        httpx2.ConnectError("refused"),
        httpx2.ReadTimeout("too slow"),
        httpx2.RemoteProtocolError("cut"),
        httpx2.Response(500, text="boom"),
        httpx2.Response(502, text="<html>bad gateway</html>"),
        httpx2.Response(503, json={"message": "starting"}),
        httpx2.Response(401, json={"message": "no"}),
        httpx2.Response(403, text="forbidden"),
        httpx2.Response(418, text="a teapot"),  # something MLflow never says
    ],
)
async def test_mlflow_that_does_not_answer_or_answers_wrongly_is_unavailable(answer) -> None:
    with pytest.raises(RegistryUnavailable) as raised:
        await registry(Server().say(answer)).create_model("ada~m")
    assert BASE not in str(raised.value) and "mlflow" not in str(raised.value).lower().replace("models service", "")


async def test_a_404_without_a_body_is_not_found_and_a_400_without_a_message_is_rejected() -> None:
    with pytest.raises(RegistryNotFound):
        await registry(Server().say(httpx2.Response(404, text="Not Found"))).get_version("ada~m", "1")
    with pytest.raises(RegistryRejected):
        await registry(Server().say(httpx2.Response(400, text="bad"))).create_model("x")


async def test_the_key_is_sent_as_a_bearer_token_and_only_when_there_is_one() -> None:
    server = Server().say(ok(), ok())
    await registry(server, api_key="secret-key").create_model("a")
    assert server.last.headers["authorization"] == "Bearer secret-key"
    await registry(server).create_model("a")
    assert "authorization" not in server.last.headers


async def test_a_server_that_is_not_configured_says_so_on_every_call() -> None:
    nothing = NoRegistry()
    with pytest.raises(RegistryUnavailable, match="not configured"):
        await nothing.create_model("a")
    with pytest.raises(RegistryUnavailable, match="not configured"):
        await nothing.list_artifacts("a", "1")


def test_the_registry_comes_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.registry import get_links, get_registry

    monkeypatch.setattr(settings, "MLFLOW_TRACKING_URI", "")
    assert isinstance(get_registry(), NoRegistry)
    monkeypatch.setattr(settings, "MLFLOW_TRACKING_URI", "http://mlflow:5000")
    assert isinstance(get_registry(), MlflowRegistry)
    monkeypatch.setattr(settings, "MLFLOW_PUBLIC_URL", "http://localhost:5000")
    assert get_links().model("ada~m") == "http://localhost:5000/#/models/ada~m"


# ---- small files in the artifacts of a run


async def test_a_small_file_is_put_in_the_artifacts_of_a_run() -> None:
    server = Server().say(httpx2.Response(200))
    await registry(server).log_artifact(RUN, "/MANIFEST.json", b"{}")
    assert (server.last.method, server.last.url.path) == (
        "PUT",
        f"/api/2.0/mlflow-artifacts/artifacts/{RUN.experiment_id}/{RUN.run_id}/artifacts/MANIFEST.json",
    )
    assert server.last.content == b"{}"


async def test_a_file_that_cannot_be_put_in_the_artifacts_is_an_error() -> None:
    with pytest.raises(RegistryUnavailable):
        await registry(Server().say(httpx2.Response(500))).log_artifact(RUN, "a", b"x")
    with pytest.raises(RegistryUnavailable):
        await registry(Server().say(httpx2.ConnectError("down"))).log_artifact(RUN, "a", b"x")
