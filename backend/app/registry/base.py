"""What the backend asks of the registry of the models. Nothing here is specific to MLflow, as nothing of `ObjectStore`
is specific to S3: the rest of the code never imports MLflow and does not know its REST shape."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RegistryRun:
    """A run of MLflow, the place where the artifacts of a version are put before it is registered."""

    experiment_id: str
    run_id: str
    # `mlflow-artifacts:/<experiment>/<run>/artifacts`
    artifact_uri: str


@dataclass(frozen=True)
class RegistryVersion:
    """A version of the Model Registry."""

    name: str
    version: str
    run_id: str | None
    # Where its artifacts are, as MLflow says it (`mlflow-artifacts:/...`).
    source: str
    status: str


@dataclass(frozen=True)
class RegistryArtifact:
    path: str
    is_dir: bool
    size: int | None


class ModelRegistry(Protocol):
    """MLflow, as the platform uses it: a registered model per model, a run to put the artifacts in, a version per
    version. Every operation can raise `RegistryUnavailable` (MLflow does not answer), `RegistryRejected` (it refuses a
    value), and `RegistryNotFound` or `RegistryConflict` where it says."""

    async def create_model(self, name: str) -> None:
        """Makes the registered model. `RegistryConflict` if the name is taken."""
        ...

    async def model_exists(self, name: str) -> bool: ...

    async def delete_model(self, name: str) -> None:
        """Deletes the registered model and its versions. Does nothing when it is already gone. The artifacts stay in
        the storage: MLflow does not delete them (see docs/mlflow.md)."""
        ...

    async def create_run(self, model_name: str) -> RegistryRun:
        """A run to put the artifacts of a new version in. The experiment of the model is made the first time."""
        ...

    async def log_artifact(self, run: RegistryRun, path: str, data: bytes) -> None:
        """Puts a small file in the artifacts of a run (a manifest, a card). Large files do not go through here."""
        ...

    async def finish_run(self, run_id: str, *, failed: bool = False) -> None: ...

    async def delete_run(self, run_id: str) -> None:
        """Does nothing when it is already gone."""
        ...

    async def create_version(self, name: str, run: RegistryRun, path: str = "") -> RegistryVersion:
        """Registers the artifacts under `path` of the run as a new version. `RegistryNotFound` if the model is not
        there."""
        ...

    async def get_version(self, name: str, version: str) -> RegistryVersion:
        """`RegistryNotFound` if it is not there."""
        ...

    async def delete_version(self, name: str, version: str) -> None:
        """Does nothing when it is already gone."""
        ...

    async def set_alias(self, name: str, alias: str, version: str) -> None:
        """`production`, `stable`...: a name that points to a version, and that can be moved."""
        ...

    async def delete_alias(self, name: str, alias: str) -> None: ...

    async def list_artifacts(self, name: str, version: str, path: str = "") -> list[RegistryArtifact]:
        """What is in one folder of the artifacts of a version (the top one by default), not what is below."""
        ...

    async def artifact_key_prefix(self, name: str, version: str) -> str:
        """The key, in the storage, under which the artifacts of a version are: the files can be read and sent there
        without going through MLflow."""
        ...
