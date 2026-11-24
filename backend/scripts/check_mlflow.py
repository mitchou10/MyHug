"""Checks that the MLflow of the compose works as the backend will use it: a registered model, a version of it, an
artifact sent through the server, read back through the server, and found in the bucket under `mlflow/`.

MLflow is not published, so this runs from inside the compose (the backend has the settings and speaks to both):

    docker compose exec -T -e PYTHONPATH=/app backend python - < backend/scripts/check_mlflow.py

It speaks to the REST API only (the backend does not install the `mlflow` package) and cleans up after itself.
"""

import asyncio
import sys
import time

import httpx2

from app.config import settings
from app.storage import get_store

API = f"{settings.MLFLOW_TRACKING_URI.rstrip('/')}/api/2.0"
CONTENT = b"an artifact of a model"


def post(client: httpx2.Client, path: str, body: dict) -> dict:
    response = client.post(f"{API}/mlflow/{path}", json=body)
    response.raise_for_status()
    return response.json()


async def main() -> int:
    if not settings.MLFLOW_TRACKING_URI:
        print("MLFLOW_TRACKING_URI is not set")
        return 1
    suffix = str(int(time.time()))
    name = f"check-{suffix}"
    headers = {"Authorization": f"Bearer {settings.MLFLOW_API_KEY}"} if settings.MLFLOW_API_KEY else {}
    with httpx2.Client(timeout=30, headers=headers) as client:
        client.get(f"{settings.MLFLOW_TRACKING_URI.rstrip('/')}/health").raise_for_status()
        print("server        : healthy")
        experiment = post(client, "experiments/create", {"name": name})["experiment_id"]
        run = post(client, "runs/create", {"experiment_id": experiment, "start_time": int(time.time() * 1000)})["run"][
            "info"
        ]["run_id"]
        path = f"{experiment}/{run}/artifacts/hello.txt"
        client.put(f"{API}/mlflow-artifacts/artifacts/{path}", content=CONTENT).raise_for_status()
        print("artifact sent : through the server, no storage key")
        back = client.get(f"{API}/mlflow-artifacts/artifacts/{path}")
        assert back.content == CONTENT, "the artifact read back is not the one that was sent"
        print("artifact read : through the server, identical")

        stored = await get_store().head(f"mlflow/{path}")
        assert stored is not None and stored.size == len(CONTENT), "the artifact is not in the bucket under mlflow/"
        print(f"in the bucket : mlflow/{path} ({stored.size} bytes)")

        post(client, "registered-models/create", {"name": name})
        version = post(
            client,
            "model-versions/create",
            {"name": name, "source": f"mlflow-artifacts:/{experiment}/{run}/artifacts", "run_id": run},
        )["model_version"]["version"]
        found = client.get(f"{API}/mlflow/model-versions/get", params={"name": name, "version": version}).json()
        assert found["model_version"]["name"] == name
        print(f"registry      : {name} version {version}")

        client.request("DELETE", f"{API}/mlflow/registered-models/delete", json={"name": name}).raise_for_status()
        post(client, "runs/delete", {"run_id": run})
        post(client, "experiments/delete", {"experiment_id": experiment})
        print("cleaned up")
    return 0


sys.exit(asyncio.run(main()))
