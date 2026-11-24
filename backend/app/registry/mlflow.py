import logging
import time
from typing import Any

import httpx2

from app.registry.base import RegistryArtifact, RegistryRun, RegistryVersion
from app.services.errors import RegistryConflict, RegistryNotFound, RegistryRejected, RegistryUnavailable

logger = logging.getLogger(__name__)
API = "/api/2.0/mlflow"
ARTIFACTS_API = "/api/2.0/mlflow-artifacts/artifacts"
SCHEME = "mlflow-artifacts:/"


class MlflowRegistry:
    """MLflow, spoken to over its REST API. The `mlflow` package is not installed in the backend (it is very large): the
    few calls the platform needs are written here, and nowhere else in the code is MLflow known."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        timeout: float = 30.0,
        artifacts_prefix: str = "mlflow/",
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout
        self._prefix = artifacts_prefix.strip("/") + "/" if artifacts_prefix.strip("/") else ""
        self._transport = transport

    # ---- the calls

    async def _call(
        self, method: str, path: str, *, params: dict | None = None, body: dict | None = None, root: str = API
    ) -> dict[str, Any]:
        try:
            async with httpx2.AsyncClient(
                base_url=self._base_url, headers=self._headers, timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.request(method, f"{root}{path}", params=params, json=body)
        except httpx2.HTTPError as error:  # not reachable, too slow, cut off
            logger.error("MLflow does not answer (%s %s): %s", method, path, error)
            raise RegistryUnavailable("The models service does not answer") from None
        if response.status_code < 400:
            return response.json() if response.content else {}
        raise self._error(method, path, response)

    @staticmethod
    def _error(method: str, path: str, response: httpx2.Response) -> Exception:
        try:
            detail = response.json()
        except ValueError:
            detail = {}
        code = detail.get("error_code") if isinstance(detail, dict) else None
        message = detail.get("message", "") if isinstance(detail, dict) else ""
        if response.status_code in (401, 403):
            logger.error("MLflow refuses the key (%s %s)", method, path)
            return RegistryUnavailable("The models service refuses the platform")
        if response.status_code >= 500:
            logger.error("MLflow failed (%s %s): %s %s", method, path, response.status_code, message)
            return RegistryUnavailable("The models service failed")
        if code == "RESOURCE_DOES_NOT_EXIST" or response.status_code == 404:
            return RegistryNotFound()
        if code == "RESOURCE_ALREADY_EXISTS":
            return RegistryConflict()
        if response.status_code == 400:
            return RegistryRejected(message or None)
        logger.error("MLflow answered %s to %s %s: %s", response.status_code, method, path, message)
        return RegistryUnavailable("The models service answered something unexpected")

    # ---- registered models

    async def create_model(self, name: str) -> None:
        await self._call("POST", "/registered-models/create", body={"name": name})

    async def model_exists(self, name: str) -> bool:
        try:
            await self._call("GET", "/registered-models/get", params={"name": name})
        except RegistryNotFound:
            return False
        return True

    async def delete_model(self, name: str) -> None:
        try:
            await self._call("DELETE", "/registered-models/delete", body={"name": name})
        except RegistryNotFound:
            return  # already gone

    # ---- runs

    async def _experiment(self, name: str) -> str:
        """The experiment of a model, made the first time. A deleted one is brought back."""
        for _ in range(2):  # the second time is for another request that made it between the two calls
            try:
                found = (await self._call("GET", "/experiments/get-by-name", params={"experiment_name": name}))[
                    "experiment"
                ]
            except RegistryNotFound:
                try:
                    return str((await self._call("POST", "/experiments/create", body={"name": name}))["experiment_id"])
                except RegistryConflict:
                    continue
            if found.get("lifecycle_stage") == "deleted":
                await self._call("POST", "/experiments/restore", body={"experiment_id": found["experiment_id"]})
            return str(found["experiment_id"])
        raise RegistryUnavailable("The models service did not give an experiment")

    async def create_run(self, model_name: str) -> RegistryRun:
        experiment = await self._experiment(model_name)
        created = await self._call(
            "POST", "/runs/create", body={"experiment_id": experiment, "start_time": int(time.time() * 1000)}
        )
        info = created["run"]["info"]
        return RegistryRun(
            experiment_id=str(info["experiment_id"]), run_id=info["run_id"], artifact_uri=info["artifact_uri"]
        )

    async def finish_run(self, run_id: str, *, failed: bool = False) -> None:
        await self._call(
            "POST",
            "/runs/update",
            body={"run_id": run_id, "status": "FAILED" if failed else "FINISHED", "end_time": int(time.time() * 1000)},
        )

    async def delete_run(self, run_id: str) -> None:
        try:
            await self._call("POST", "/runs/delete", body={"run_id": run_id})
        except RegistryNotFound:
            return

    # ---- versions

    @staticmethod
    def _version(raw: dict[str, Any]) -> RegistryVersion:
        return RegistryVersion(
            name=raw["name"],
            version=str(raw["version"]),
            run_id=raw.get("run_id") or None,
            source=raw.get("source", ""),
            status=raw.get("status", ""),
        )

    async def create_version(self, name: str, run: RegistryRun, path: str = "") -> RegistryVersion:
        path = path.strip("/")
        source = f"{run.artifact_uri.rstrip('/')}/{path}" if path else run.artifact_uri
        created = await self._call(
            "POST", "/model-versions/create", body={"name": name, "source": source, "run_id": run.run_id}
        )
        return self._version(created["model_version"])

    async def get_version(self, name: str, version: str) -> RegistryVersion:
        found = await self._call("GET", "/model-versions/get", params={"name": name, "version": version})
        return self._version(found["model_version"])

    async def delete_version(self, name: str, version: str) -> None:
        try:
            await self._call("DELETE", "/model-versions/delete", body={"name": name, "version": version})
        except RegistryNotFound:
            return

    async def set_alias(self, name: str, alias: str, version: str) -> None:
        await self._call("POST", "/registered-models/alias", body={"name": name, "alias": alias, "version": version})

    async def delete_alias(self, name: str, alias: str) -> None:
        await self._call("DELETE", "/registered-models/alias", body={"name": name, "alias": alias})

    # ---- artifacts

    async def _root(self, name: str, version: str) -> str:
        """Where the artifacts of a version are in MLflow, without the scheme: `<experiment>/<run>/artifacts/<path>`."""
        uri = (await self._call("GET", "/model-versions/get-download-uri", params={"name": name, "version": version}))[
            "artifact_uri"
        ]
        if not uri.startswith(SCHEME):
            raise RegistryRejected("The artifacts of this version are not kept by the models service")
        return uri.removeprefix(SCHEME).strip("/")

    async def list_artifacts(self, name: str, version: str, path: str = "") -> list[RegistryArtifact]:
        root = await self._root(name, version)
        folder = path.strip("/")
        listed = await self._call(
            "GET", "", params={"path": f"{root}/{folder}" if folder else root}, root=ARTIFACTS_API
        )
        return [
            RegistryArtifact(
                path=f"{folder}/{item['path']}" if folder else item["path"],
                is_dir=bool(item.get("is_dir")),
                size=item.get("file_size"),
            )
            for item in listed.get("files", [])
        ]

    async def artifact_key_prefix(self, name: str, version: str) -> str:
        return f"{self._prefix}{await self._root(name, version)}/"
