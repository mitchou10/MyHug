"""The metrics of every task: what an evaluation holds. The platform defines them, and this reads them."""

from myhug._models import MetricOut, TaskMetricsOut
from myhug.aclient import AsyncClient
from myhug.client import Client

Ids = list[str]  # the name `list` is a method of the classes below


def find(tasks: list[TaskMetricsOut], task: str) -> TaskMetricsOut:
    for found in tasks:
        if found.task == task:
            return found
    raise ValueError(f"No task {task!r}: the tasks are {', '.join(t.task for t in tasks)}")


class Metrics:
    """`client.metrics`."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list(self) -> list[TaskMetricsOut]:
        """Every task with its metrics (id, name, higher is better, the main one) and the ones shown by default."""
        return [TaskMetricsOut.model_validate(t) for t in self._client.json("GET", "/api/metrics")]

    def get(self, task: str) -> TaskMetricsOut:
        return find(self.list(), task)

    def ids(self, task: str) -> Ids:
        """The ids of the metrics of a task: what the keys of a result may be."""
        return [m.id for m in self.get(task).metrics]


class AsyncMetrics:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list(self) -> list[TaskMetricsOut]:
        return [TaskMetricsOut.model_validate(t) for t in await self._client.json("GET", "/api/metrics")]

    async def get(self, task: str) -> TaskMetricsOut:
        return find(await self.list(), task)

    async def ids(self, task: str) -> Ids:
        return [m.id for m in (await self.get(task)).metrics]


__all__ = ["AsyncMetrics", "MetricOut", "Metrics"]
