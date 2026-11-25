"""A model, as a program uses it: look at it, change it, send versions (files, code, or both), download them, try it."""

import math
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from myhug import _plan, _predictions
from myhug._download import download
from myhug._models import (
    CodeIn,
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
from myhug._upload import Routes, upload
from myhug.client import Client
from myhug.datasets import DONE, POLL_SECONDS, split_address
from myhug.errors import ConnectionFailed, EvaluationFailed, MyHugError, UploadError, VersionFailed, WaitTimeout
from myhug.hardware import detect

EVALUATIONS_PAGE = 50


def _start_body(**given: Any) -> dict[str, Any]:
    """What starts an evaluation: only what is given, the platform has a default for the rest."""
    return {key: value for key, value in given.items() if value is not None}


def _inference(seconds: float | None, hardware: dict[str, Any] | bool | None) -> dict[str, Any] | None:
    """How the predictions were made, as it is sent: the time, and the hardware (read from this machine for `True`)."""
    if seconds is not None and (
        isinstance(seconds, bool) or not isinstance(seconds, int | float) or not math.isfinite(seconds) or seconds < 0
    ):
        raise ValueError(f"The time of the inference must be a number of seconds, not {seconds!r}")
    described = detect() if hardware is True else (hardware or None)
    given = {"seconds": float(seconds) if seconds is not None else None, "hardware": described}
    return {key: value for key, value in given.items() if value is not None} or None


def interrupted(error: MyHugError, evaluation_id: UUID) -> MyHugError:
    """The same error, saying which evaluation to go on with: its id is all that is needed to send the rest."""
    return type(error)(
        f"{error} (evaluation {evaluation_id}: `model.send_predictions('{evaluation_id}', predictions)`)"
    )


Code = CodeIn | dict[str, Any]


def code_body(code: Code | None) -> dict[str, Any] | None:
    """The reference to code a version carries: a repository (`url`), and optionally `ref`, `path`, `entrypoint`. It is
    only a link: the platform pins it to its exact commit afterwards (`version.code.sha`)."""
    if code is None:
        return None
    return (
        code.model_dump(exclude_none=True, mode="json")
        if isinstance(code, CodeIn)
        else {k: v for k, v in code.items() if v is not None}
    )


class Models:
    """`client.models`: the models I can see, one by its address, and a new one."""

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

    def get(self, address: str) -> "Model":
        owner, name = split_address(address)
        return Model(self._client, ModelOut.model_validate(self._client.json("GET", f"/api/models/{owner}/{name}")))

    def create(self, name: str, *, tasks: Sequence[str], inputs: Sequence[str], **fields: Any) -> "Model":
        """A model in my name. `tasks` is what it does (`ner`...), `inputs` the kinds of data it reads (`text`...)."""
        body = {"name": name, "tasks": list(tasks), "inputs": list(inputs), **fields}
        return Model(self._client, ModelOut.model_validate(self._client.json("POST", "/api/models", json=body)))


class Model:
    def __init__(self, client: Client, info: ModelOut) -> None:
        self._client = client
        self.info = info

    def __repr__(self) -> str:
        return f"Model({self.address!r})"

    @property
    def address(self) -> str:
        return f"{self.info.owner}/{self.info.name}"

    @property
    def _base(self) -> str:
        return f"/api/models/{self.info.owner}/{self.info.name}"

    # ---- the model itself

    def refresh(self) -> Self:
        self.info = ModelOut.model_validate(self._client.json("GET", self._base))
        return self

    def update(self, **changes: Any) -> Self:
        """Changes `description`, `library`, `languages`, `license`, `tags`, `visibility`, `card`, `code_url`,
        `parameters`, `trained_on`: what is not given stays. The name, the tasks and the inputs never change."""
        self.info = ModelOut.model_validate(self._client.json("PATCH", self._base, json=changes))
        return self

    def delete(self) -> None:
        self._client.json("DELETE", self._base)

    def like(self) -> int:
        return self._client.json("PUT", f"{self._base}/like")["likes"]

    def unlike(self) -> int:
        return self._client.json("DELETE", f"{self._base}/like")["likes"]

    # ---- who has access, and where it is served (for the people who can edit it)

    def members(self) -> list[MemberOut]:
        return [MemberOut.model_validate(m) for m in self._client.json("GET", f"{self._base}/members")]

    def set_member(self, user_id: str, role: str) -> MemberOut:
        """Gives access (`reader`, or `maintainer` who can also change it), or changes the role."""
        return MemberOut.model_validate(
            self._client.json("PUT", f"{self._base}/members/{user_id}", json={"role": role})
        )

    def remove_member(self, user_id: str) -> None:
        self._client.json("DELETE", f"{self._base}/members/{user_id}")

    def endpoint(self) -> EndpointOut:
        return EndpointOut.model_validate(self._client.json("GET", f"{self._base}/endpoint"))

    def set_endpoint(self, **endpoint: Any) -> EndpointOut:
        """Says where the model is served (`kind`, `url`, `input_kind`, `output_kind`...): see `PUT .../endpoint`."""
        return EndpointOut.model_validate(self._client.json("PUT", f"{self._base}/endpoint", json=endpoint))

    def remove_endpoint(self) -> None:
        self._client.json("DELETE", f"{self._base}/endpoint")

    def predict(self, input: Any) -> PredictOut:
        """Tries the model: the platform relays the input to the server that serves it. Only for a served model."""
        return PredictOut.model_validate(
            self._client.json("POST", f"{self._base}/predict", json={"input": input}, retry=False)
        )

    # ---- versions and files

    def versions(self) -> list[ModelVersionOut]:
        """The versions, the newest first."""
        return [ModelVersionOut.model_validate(v) for v in self._client.json("GET", f"{self._base}/versions")]

    def _latest(self) -> int:
        self.refresh()
        if not self.info.version:
            raise ValueError(f"{self.address} has no version yet")
        return self.info.version

    def version(self, number: int | None = None) -> ModelVersionDetailOut:
        """One version with its files (the latest by default)."""
        found = self._client.json("GET", f"{self._base}/versions/{number or self._latest()}")
        return ModelVersionDetailOut.model_validate(found)

    def files(self, version: int | None = None) -> list[ModelFileOut]:
        return self.version(version).files

    def download(
        self,
        to: str | Path | None = None,
        *,
        version: int | None = None,
        path: str | None = None,
        progress: ProgressCallback | None = None,
        parallel: int = PARALLEL,
    ) -> list[Path]:
        """Downloads the files of a version (the latest by default), or one `path`, under `to` with the path they
        have in the version (by default in the cache of the SDK). Resumed if interrupted, and checked once the
        platform knows their fingerprint."""
        detail = self.version(version)
        files = _plan.select(detail.files, split=None, path=path, known_splits=())
        folder = (
            Path(to)
            if to
            else cache_folder(self._client.cache_dir) / "models" / self.info.owner / self.info.name / str(detail.number)
        )
        jobs = [(f, _plan.inside(folder, f.path)) for f in files]

        def fetch(job: tuple[ModelFileOut, Path]) -> Path:
            file, dest = job
            return download(
                self._client,
                f"{self._base}/files/{file.path}",
                dest,
                size=file.size_bytes,
                sha256=file.sha256,
                progress=progress,
                params={"version": detail.number},
            )

        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            return list(pool.map(fetch, jobs))

    # ---- new versions

    def upload_version(
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
        """A new version made of `files` (each under its name), a `folder` (each file under its path in it), a
        reference to `code`, or any of them together; `remove` takes paths out of what the latest version holds. The
        files go straight to the storage in parts and the upload goes on if it is interrupted and run again. With
        `wait=True` it waits until the platform has read them (`VersionFailed` if it could not)."""
        local: dict[str, LocalFile] = {}
        for source in files:
            file = Path(source)
            if not file.is_file():
                raise ValueError(f"{file} is not a file")
            local[_plan.remote_path(file.name)] = LocalFile(file, _plan.remote_path(file.name))
        if folder is not None:
            for entry in _plan.walk(Path(folder), ignore=ignore):
                local[entry.path] = entry
        if not local and not remove and code is None:
            raise ValueError("A version needs files, a reference to code, or paths to remove")
        if not local and not remove:
            return self.create_code_version(code, message=message, wait=wait)  # ty: ignore[invalid-argument-type]
        done = upload(
            self._client,
            Routes(f"{self._base}/uploads", "/api/model-uploads"),
            list(local.values()),
            message=message,
            remove=[_plan.remote_path(p) for p in remove],
            extra={"code": code_body(code)} if code is not None else None,
            progress=progress,
        )
        self.refresh()
        return self._finish(ModelVersionOut.model_validate(done), wait)

    def create_code_version(self, code: Code, *, message: str = "", wait: bool = False) -> ModelVersionOut:
        """A version that is only a link to code (nothing is uploaded)."""
        created = self._client.json(
            "POST", f"{self._base}/versions", json={"code": code_body(code), "message": message}, retry=False
        )
        self.refresh()
        return self._finish(ModelVersionOut.model_validate(created), wait)

    def _finish(self, version: ModelVersionOut, wait: bool) -> ModelVersionOut:
        return self.wait(version.number) if wait else version

    def delete_version(self, number: int) -> None:
        self._client.json("DELETE", f"{self._base}/versions/{number}")
        self.refresh()

    def wait(self, version: int | None = None, *, timeout: float = 600.0) -> ModelVersionOut:
        """Waits until the platform has read the files of a version: `ready`, or it raises `VersionFailed`. The
        pinning of its code to a commit is separate: `version.code.state`."""
        number = version or self._latest()
        waited = 0.0
        while True:
            found = next((v for v in self.versions() if v.number == number), None)
            if found is not None and found.status in DONE:
                if found.status == "failed":
                    raise VersionFailed(number, found.error)
                return found
            if waited >= timeout:
                raise WaitTimeout(f"Version {number} of {self.address} is still being read after {timeout:.0f} s")
            self._client._sleep(POLL_SECONDS)
            waited += POLL_SECONDS

    # ---- evaluations

    def evaluations(self, *, task: str | None = None, version: int | None = None) -> list[EvaluationOut]:
        """The evaluations of the model, the newest first (of a task, of a version of the model). What each one holds
        depends on who asks: all the metrics for the people who can edit the model, the chosen ones for the others."""
        found: list[EvaluationOut] = []
        while True:
            params = {"task": task, "version": version, "limit": EVALUATIONS_PAGE, "offset": len(found)}
            page = self._client.json("GET", f"{self._base}/evaluations", params=params)
            found.extend(EvaluationOut.model_validate(e) for e in page)
            if len(page) < EVALUATIONS_PAGE:
                return found

    def evaluation(self, evaluation_id: str | UUID) -> EvaluationOut:
        return EvaluationOut.model_validate(self._client.json("GET", f"{self._base}/evaluations/{evaluation_id}"))

    def evaluate(
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
                self._client.json(
                    "POST",
                    f"{self._base}/evaluations",
                    json=_start_body(
                        version=self._latest() if version is None else version,
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
                sent = self._send(started.id, prepared.path, progress)
            except (UploadError, ConnectionFailed) as error:
                raise interrupted(error, started.id) from None
        return self.wait_evaluation(sent.id, timeout=timeout) if wait else sent

    def send_predictions(
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
            return self._send(evaluation_id, prepared.path, progress)

    def _send(self, evaluation_id: str | UUID, path: Path, progress: ProgressCallback | None) -> EvaluationOut:
        base = f"{self._base}/evaluations/{evaluation_id}"
        done = _predictions.send(self._client, base, path, progress=progress)
        return EvaluationOut.model_validate(done)

    def wait_evaluation(self, evaluation_id: str | UUID, *, timeout: float = 600.0) -> EvaluationOut:
        """Waits until a worker has computed the metrics: `done`, or it raises `EvaluationFailed` (or `WaitTimeout`)."""
        waited = 0.0
        while True:
            found = self.evaluation(evaluation_id)
            if found.status in ("done", "stopped"):
                return found
            if found.status == "failed":
                raise EvaluationFailed(str(evaluation_id), found.error)
            if waited >= timeout:
                raise WaitTimeout(f"The evaluation {evaluation_id} is still {found.status} after {timeout:.0f} s")
            self._client._sleep(POLL_SECONDS)
            waited += POLL_SECONDS

    def set_shown(self, evaluation_id: str | UUID, shown: Sequence[str]) -> EvaluationOut:
        """Chooses the metrics the others see (the result keeps all of them)."""
        done = self._client.json("PUT", f"{self._base}/evaluations/{evaluation_id}/shown", json={"shown": list(shown)})
        return EvaluationOut.model_validate(done)

    def delete_evaluation(self, evaluation_id: str | UUID) -> None:
        self._client.json("DELETE", f"{self._base}/evaluations/{evaluation_id}")
