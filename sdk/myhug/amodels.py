"""The same as `models.py`, for asyncio."""

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from myhug import _plan, _predictions
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
from myhug.errors import ConnectionFailed, EvaluationFailed, UploadError, VersionFailed, WaitTimeout
from myhug.models import EVALUATIONS_PAGE, Code, _inference, _start_body, code_body, interrupted


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

    async def evaluate(
        self,
        task: str,
        predictions: str | Path | Iterable[Any],
        *,
        dataset: str,
        split: str,
        target_column: str,
        version: int | None = None,
        dataset_version: int | None = None,
        key_column: str | None = None,
        input_column: str | None = None,
        prediction_column: str = "prediction",
        note: str = "",
        inference_seconds: float | None = None,
        hardware: dict[str, Any] | bool | None = None,
        wait: bool = False,
        timeout: float = 600.0,
        progress: ProgressCallback | None = None,
    ) -> EvaluationOut:
        """Evaluates a version of the model on a split of a dataset from the **predictions** you made with it.

        The platform computes the metrics, always (a worker does): you send what the model answered, never a score.
        `predictions` is a `.jsonl`, `.csv` or `.parquet` file, or a list with one value (or one object) for each item
        of the split, in its order. They are compared to `target_column` of `dataset` (`owner/name`, a dataset you can
        read); `key_column`, a column of the dataset that identifies each item, says which item a line is about
        (empty: the position of the line). Only the people who can edit the model may do it; the version is the latest
        one unless you say. The predictions go straight to the storage in parts: if it is interrupted,
        `model.send_predictions(evaluation.id, predictions)` goes on. With `wait=True` it waits for the metrics
        (`EvaluationFailed` if the predictions do not match the split).

        `inference_seconds` is the time your model took to make them (`with myhug.Stopwatch() as watch: ...`), and
        `hardware` what it ran on: a dict (see `myhug.hardware.detect()`), or `True` to read this machine. Both are
        shown with the evaluation as **declared by you**: the platform cannot check them."""
        inference = _inference(inference_seconds, hardware)  # before anything is asked of the platform
        with _predictions.prepare(predictions, folder=self._client.cache_dir, column=prediction_column) as prepared:
            started = EvaluationOut.model_validate(
                await self._client.json(
                    "POST",
                    f"{self._base}/evaluations",
                    json=_start_body(
                        version=await self._latest() if version is None else version,
                        task=task,
                        dataset=dataset,
                        dataset_version=dataset_version,
                        split=split,
                        target_column=target_column,
                        key_column=key_column,
                        input_column=input_column,
                        prediction_column=prediction_column,
                        format=prepared.format,
                        size=prepared.path.stat().st_size,
                        note=note,
                        inference=inference,
                    ),
                    retry=False,
                )
            )
            try:
                sent = await self._send(started.id, prepared.path, progress)
            except (UploadError, ConnectionFailed) as error:
                raise interrupted(error, started.id) from None
        return await self.wait_evaluation(sent.id, timeout=timeout) if wait else sent

    async def send_predictions(
        self,
        evaluation_id: str | UUID,
        predictions: str | Path | Iterable[Any],
        *,
        prediction_column: str = "prediction",
        progress: ProgressCallback | None = None,
    ) -> EvaluationOut:
        """Sends the predictions of an evaluation that was started (again, after an interruption): only the parts that
        are not in the storage go. The file must be the one that was announced."""
        with _predictions.prepare(predictions, folder=self._client.cache_dir, column=prediction_column) as prepared:
            return await self._send(evaluation_id, prepared.path, progress)

    async def _send(self, evaluation_id: str | UUID, path: Path, progress: ProgressCallback | None) -> EvaluationOut:
        base = f"{self._base}/evaluations/{evaluation_id}"
        done = await _predictions.asend(self._client, base, path, progress=progress)
        return EvaluationOut.model_validate(done)

    async def wait_evaluation(self, evaluation_id: str | UUID, *, timeout: float = 600.0) -> EvaluationOut:
        """Waits until a worker has computed the metrics: `done`, or it raises `EvaluationFailed` (or `WaitTimeout`)."""
        waited = 0.0
        while True:
            found = await self.evaluation(evaluation_id)
            if found.status in ("done", "stopped"):
                return found
            if found.status == "failed":
                raise EvaluationFailed(str(evaluation_id), found.error)
            if waited >= timeout:
                raise WaitTimeout(f"The evaluation {evaluation_id} is still {found.status} after {timeout:.0f} s")
            await self._client._sleep(POLL_SECONDS)
            waited += POLL_SECONDS

    async def set_shown(self, evaluation_id: str | UUID, shown: Sequence[str]) -> EvaluationOut:
        """Chooses the metrics the others see (the result keeps all of them)."""
        done = await self._client.json(
            "PUT", f"{self._base}/evaluations/{evaluation_id}/shown", json={"shown": list(shown)}
        )
        return EvaluationOut.model_validate(done)

    async def delete_evaluation(self, evaluation_id: str | UUID) -> None:
        await self._client.json("DELETE", f"{self._base}/evaluations/{evaluation_id}")
