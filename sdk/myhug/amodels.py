"""The same as `models.py`, for asyncio."""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from myhug import _evaluations, _plan
from myhug._download import adownload
from myhug._models import (
    EndpointOut,
    EvaluationOut,
    MemberOut,
    ModelFileOut,
    ModelOut,
    ModelSummaryOut,
    ModelVersionDetailOut,
    ModelVersionOut,
    PredictOut,
)
from myhug._transfer import PARALLEL, LocalFile, ProgressCallback, cache_folder
from myhug._upload import Routes, aupload
from myhug.aclient import AsyncClient
from myhug.datasets import DONE, POLL_SECONDS, split_address
from myhug.errors import VersionFailed, WaitTimeout
from myhug.models import EVALUATIONS_PAGE, Code, code_body


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

    async def get(self, address: str) -> "AsyncModel":
        owner, name = split_address(address)
        return AsyncModel(
            self._client, ModelOut.model_validate(await self._client.json("GET", f"/api/models/{owner}/{name}"))
        )

    async def create(self, name: str, *, tasks: Sequence[str], inputs: Sequence[str], **fields: Any) -> "AsyncModel":
        body = {"name": name, "tasks": list(tasks), "inputs": list(inputs), **fields}
        return AsyncModel(
            self._client, ModelOut.model_validate(await self._client.json("POST", "/api/models", json=body))
        )


class AsyncModel:
    def __init__(self, client: AsyncClient, info: ModelOut) -> None:
        self._client = client
        self.info = info

    def __repr__(self) -> str:
        return f"AsyncModel({self.address!r})"

    @property
    def address(self) -> str:
        return f"{self.info.owner}/{self.info.name}"

    @property
    def _base(self) -> str:
        return f"/api/models/{self.info.owner}/{self.info.name}"

    async def refresh(self) -> Self:
        self.info = ModelOut.model_validate(await self._client.json("GET", self._base))
        return self

    async def update(self, **changes: Any) -> Self:
        self.info = ModelOut.model_validate(await self._client.json("PATCH", self._base, json=changes))
        return self

    async def delete(self) -> None:
        await self._client.json("DELETE", self._base)

    async def like(self) -> int:
        return (await self._client.json("PUT", f"{self._base}/like"))["likes"]

    async def unlike(self) -> int:
        return (await self._client.json("DELETE", f"{self._base}/like"))["likes"]

    async def members(self) -> list[MemberOut]:
        return [MemberOut.model_validate(m) for m in await self._client.json("GET", f"{self._base}/members")]

    async def set_member(self, user_id: str, role: str) -> MemberOut:
        found = await self._client.json("PUT", f"{self._base}/members/{user_id}", json={"role": role})
        return MemberOut.model_validate(found)

    async def remove_member(self, user_id: str) -> None:
        await self._client.json("DELETE", f"{self._base}/members/{user_id}")

    async def endpoint(self) -> EndpointOut:
        return EndpointOut.model_validate(await self._client.json("GET", f"{self._base}/endpoint"))

    async def set_endpoint(self, **endpoint: Any) -> EndpointOut:
        return EndpointOut.model_validate(await self._client.json("PUT", f"{self._base}/endpoint", json=endpoint))

    async def remove_endpoint(self) -> None:
        await self._client.json("DELETE", f"{self._base}/endpoint")

    async def predict(self, input: Any) -> PredictOut:
        answer = await self._client.json("POST", f"{self._base}/predict", json={"input": input}, retry=False)
        return PredictOut.model_validate(answer)

    async def versions(self) -> list[ModelVersionOut]:
        return [ModelVersionOut.model_validate(v) for v in await self._client.json("GET", f"{self._base}/versions")]

    async def _latest(self) -> int:
        await self.refresh()
        if not self.info.version:
            raise ValueError(f"{self.address} has no version yet")
        return self.info.version

    async def version(self, number: int | None = None) -> ModelVersionDetailOut:
        found = await self._client.json("GET", f"{self._base}/versions/{number or await self._latest()}")
        return ModelVersionDetailOut.model_validate(found)

    async def files(self, version: int | None = None) -> list[ModelFileOut]:
        return (await self.version(version)).files

    async def download(
        self,
        to: str | Path | None = None,
        *,
        version: int | None = None,
        path: str | None = None,
        progress: ProgressCallback | None = None,
        parallel: int = PARALLEL,
    ) -> list[Path]:
        detail = await self.version(version)
        files = _plan.select(detail.files, split=None, path=path, known_splits=())
        base = cache_folder(self._client.cache_dir) / "models" / self.info.owner / self.info.name / str(detail.number)
        folder = Path(to) if to else base
        gate = asyncio.Semaphore(max(1, parallel))

        async def one(file: ModelFileOut) -> Path:
            async with gate:
                return await adownload(
                    self._client,
                    f"{self._base}/files/{file.path}",
                    _plan.inside(folder, file.path),
                    size=file.size_bytes,
                    sha256=file.sha256,
                    progress=progress,
                    params={"version": detail.number},
                )

        return list(await asyncio.gather(*(one(f) for f in files)))

    async def upload_version(
        self,
        files: Sequence[str | Path] = (),
        *,
        folder: str | Path | None = None,
        code: Code | None = None,
        remove: Sequence[str] = (),
        message: str = "",
        wait: bool = False,
        progress: ProgressCallback | None = None,
        ignore: Sequence[str] = _plan.DEFAULT_IGNORE,
    ) -> ModelVersionOut:
        local: dict[str, LocalFile] = {}
        for source in files:
            file = Path(source)
            if not file.is_file():
                raise ValueError(f"{file} is not a file")
            local[_plan.remote_path(file.name)] = LocalFile(file, _plan.remote_path(file.name))
        if folder is not None:
            for entry in await asyncio.to_thread(_plan.walk, Path(folder), ignore=ignore):
                local[entry.path] = entry
        if not local and not remove and code is None:
            raise ValueError("A version needs files, a reference to code, or paths to remove")
        if not local and not remove:
            return await self.create_code_version(code, message=message, wait=wait)  # ty: ignore[invalid-argument-type]
        done = await aupload(
            self._client,
            Routes(f"{self._base}/uploads", "/api/model-uploads"),
            list(local.values()),
            message=message,
            remove=[_plan.remote_path(p) for p in remove],
            extra={"code": code_body(code)} if code is not None else None,
            progress=progress,
        )
        await self.refresh()
        return await self._finish(ModelVersionOut.model_validate(done), wait)

    async def create_code_version(self, code: Code, *, message: str = "", wait: bool = False) -> ModelVersionOut:
        body = {"code": code_body(code), "message": message}
        created = await self._client.json("POST", f"{self._base}/versions", json=body, retry=False)
        await self.refresh()
        return await self._finish(ModelVersionOut.model_validate(created), wait)

    async def _finish(self, version: ModelVersionOut, wait: bool) -> ModelVersionOut:
        return await self.wait(version.number) if wait else version

    async def delete_version(self, number: int) -> None:
        await self._client.json("DELETE", f"{self._base}/versions/{number}")
        await self.refresh()

    async def wait(self, version: int | None = None, *, timeout: float = 600.0) -> ModelVersionOut:
        number = version or await self._latest()
        waited = 0.0
        while True:
            found = next((v for v in await self.versions() if v.number == number), None)
            if found is not None and found.status in DONE:
                if found.status == "failed":
                    raise VersionFailed(number, found.error)
                return found
            if waited >= timeout:
                raise WaitTimeout(f"Version {number} of {self.address} is still being read after {timeout:.0f} s")
            await self._client._sleep(POLL_SECONDS)
            waited += POLL_SECONDS

    # ---- evaluations

    async def evaluations(self, *, task: str | None = None, version: int | None = None) -> list[EvaluationOut]:
        """The evaluations of the model, the newest first (of a task, of a version of the model). What each one holds
        depends on who asks: all the metrics for the people who can edit the model, the chosen ones for the others."""
        found: list[EvaluationOut] = []
        while True:
            params = {"task": task, "version": version, "limit": EVALUATIONS_PAGE, "offset": len(found)}
            page = await self._client.json("GET", f"{self._base}/evaluations", params=params)
            found.extend(EvaluationOut.model_validate(e) for e in page)
            if len(page) < EVALUATIONS_PAGE:
                return found

    async def evaluation(self, evaluation_id: str | UUID) -> EvaluationOut:
        return EvaluationOut.model_validate(await self._client.json("GET", f"{self._base}/evaluations/{evaluation_id}"))

    async def submit_evaluation(
        self,
        task: str,
        results: Mapping[str, float],
        *,
        version: int | None = None,
        shown: Sequence[str] | None = None,
        dataset: str | None = None,
        dataset_version: int | None = None,
        split: str | None = None,
        input_column: str | None = None,
        target_column: str | None = None,
        items: int | None = None,
        note: str = "",
    ) -> EvaluationOut:
        """Sends the result of an evaluation you computed (a notebook, a training job): `results` is
        `{metric id: value}` with the metrics of the task (`client.metrics.ids(task)`). It is kept and shown as
        **sent**, never as measured. Only the people who can edit the model may send one. `version` is the latest
        one unless you say; `shown` the metrics the others see (the main one and the next by default); `dataset` an
        `owner/name` you can read; `note` how you obtained it."""
        checked = _evaluations.checked_results(results)  # before anything is asked of the platform
        sent = _evaluations.body(
            version=version or await self._latest(),
            task=task,
            results=checked,
            shown=shown,
            dataset=dataset,
            dataset_version=dataset_version,
            split=split,
            input_column=input_column,
            target_column=target_column,
            items=items,
            note=note,
        )
        return EvaluationOut.model_validate(
            await self._client.json("POST", f"{self._base}/evaluations", json=sent, retry=False)
        )

    async def set_shown(self, evaluation_id: str | UUID, shown: Sequence[str]) -> EvaluationOut:
        """Chooses the metrics the others see (the result keeps all of them)."""
        done = await self._client.json(
            "PUT", f"{self._base}/evaluations/{evaluation_id}/shown", json={"shown": list(shown)}
        )
        return EvaluationOut.model_validate(done)

    async def delete_evaluation(self, evaluation_id: str | UUID) -> None:
        await self._client.json("DELETE", f"{self._base}/evaluations/{evaluation_id}")
