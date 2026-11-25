"""What a client gives access to: datasets and models. Here only the lists; the rest comes with the resources."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

from myhug._models import DatasetSummaryOut, ModelSummaryOut
from myhug.aclient import AsyncClient
from myhug.client import Client


class Datasets:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list(
        self,
        *,
        q: str | None = None,
        owner: str | None = None,
        modality: str | None = None,
        sort: str | None = None,
    ) -> Iterator[DatasetSummaryOut]:
        """The datasets I can see, page after page (the next page is asked for when the loop gets there)."""
        params: dict[str, Any] = {"q": q, "owner": owner, "modality": modality, "sort": sort}
        for item in self._client.paginate("/api/datasets", params):
            yield DatasetSummaryOut.model_validate(item)


class Models:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list(
        self,
        *,
        q: str | None = None,
        owner: str | None = None,
        task: str | None = None,
        modality: str | None = None,
        sort: str | None = None,
    ) -> Iterator[ModelSummaryOut]:
        params: dict[str, Any] = {"q": q, "owner": owner, "task": task, "modality": modality, "sort": sort}
        for item in self._client.paginate("/api/models", params):
            yield ModelSummaryOut.model_validate(item)


class AsyncDatasets:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list(
        self,
        *,
        q: str | None = None,
        owner: str | None = None,
        modality: str | None = None,
        sort: str | None = None,
    ) -> AsyncIterator[DatasetSummaryOut]:
        params: dict[str, Any] = {"q": q, "owner": owner, "modality": modality, "sort": sort}
        async for item in self._client.paginate("/api/datasets", params):
            yield DatasetSummaryOut.model_validate(item)


class AsyncModels:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list(
        self,
        *,
        q: str | None = None,
        owner: str | None = None,
        task: str | None = None,
        modality: str | None = None,
        sort: str | None = None,
    ) -> AsyncIterator[ModelSummaryOut]:
        params: dict[str, Any] = {"q": q, "owner": owner, "task": task, "modality": modality, "sort": sort}
        async for item in self._client.paginate("/api/models", params):
            yield ModelSummaryOut.model_validate(item)
