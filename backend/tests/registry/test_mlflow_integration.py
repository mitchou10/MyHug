"""Against the real MLflow of the compose. Not run by default (CI has no MLflow): set the address of one to run it, from
your machine, where the compose publishes it on the loopback:

    MLFLOW_INTEGRATION_URL=http://localhost:5000 uv run pytest -m integration tests/registry/test_mlflow_integration.py
"""

import os
import uuid

import pytest

from app.registry import MlflowRegistry, registered_name
from app.registry.compensation import registered_model, registered_run, registered_version
from app.services.errors import RegistryConflict, RegistryNotFound, RegistryRejected

URL = os.environ.get("MLFLOW_INTEGRATION_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="set MLFLOW_INTEGRATION_URL to the address of a MLflow to run this"),
]


@pytest.fixture
def real() -> MlflowRegistry:
    return MlflowRegistry(URL, artifacts_prefix="mlflow/")


async def test_a_model_goes_through_the_real_registry(real: MlflowRegistry) -> None:
    name = registered_name("itest", uuid.uuid4().hex[:8])
    async with registered_model(real, name):
        assert await real.model_exists(name)
        with pytest.raises(RegistryConflict):
            await real.create_model(name)
        async with registered_run(real, name) as run:
            await real.log_artifact(run, "model/MLmodel", b"flavors: {}")
            async with registered_version(real, name, run, "model") as version:
                assert (await real.get_version(name, version.version)).run_id == run.run_id
                assert [a.path for a in await real.list_artifacts(name, version.version)] == ["MLmodel"]
                prefix = await real.artifact_key_prefix(name, version.version)
                assert prefix == f"mlflow/{run.experiment_id}/{run.run_id}/artifacts/model/"
                await real.set_alias(name, "production", version.version)
                await real.delete_alias(name, "production")
    await real.delete_model(name)  # the block above keeps it: the test ends it
    assert not await real.model_exists(name)
    await real.delete_model(name)  # twice is fine


async def test_the_real_registry_refuses_a_name_with_a_slash(real: MlflowRegistry) -> None:
    with pytest.raises(RegistryRejected):
        await real.create_model("ada/not-allowed")


async def test_a_version_of_a_model_that_is_not_there_is_not_found(real: MlflowRegistry) -> None:
    with pytest.raises(RegistryNotFound):
        await real.get_version(registered_name("itest", "nothing-" + uuid.uuid4().hex[:6]), "1")


async def test_a_version_can_be_a_manifest_alone(real: MlflowRegistry) -> None:
    """What the platform registers for a model: a run whose artifacts are only the list of the files (the weights stay
    in the storage of the platform), and the version is the whole run."""
    name = registered_name("itest", uuid.uuid4().hex[:8])
    async with registered_model(real, name):
        async with registered_run(real, name) as run:
            await real.log_artifact(run, "MANIFEST.json", b'{"files": []}')
            async with registered_version(real, name, run) as version:
                assert [a.path for a in await real.list_artifacts(name, version.version)] == ["MANIFEST.json"]
    await real.delete_model(name)
