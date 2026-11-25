import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.metrics import computed_for, metrics_for
from app.models import ModelEvaluation
from app.models.model_evaluation import DONE, FAILED, RUNNING
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.model_evaluations import ModelEvaluationRepository
from app.services.errors import EvaluationNotFound, InvalidEvaluation, NotBeingProcessed
from app.storage import ObjectStore

logger = logging.getLogger(__name__)
# An evaluation that has waited less than this is left alone: the job that was queued for it is about to start.
GRACE = timedelta(minutes=2)


@dataclass(frozen=True)
class FileToRead:
    path: str
    url: str
    size_bytes: int


@dataclass(frozen=True)
class ToCompute:
    """What a worker needs to compute an evaluation: where the predictions and the ground truth are (signed addresses
    of short life), how to read them and join them, and which metrics to give."""

    id: uuid.UUID
    task: str
    split: str
    target_column: str
    key_column: str | None
    prediction_column: str
    predictions: FileToRead
    predictions_format: str
    # The files of the split, in the order of the items: the line of the predictions is the position of the item.
    truth: list[FileToRead]
    metrics: list[str]


class EvaluationProcessing:
    """What the worker asks of the API while it computes the metrics of an evaluation. The worker reads the predictions
    and the ground truth and computes (it has no database); the API takes the evaluation in hand for one worker only,
    keeps what it found, and decides what a result is allowed to be.

    - `claim`: one worker at a time (a second call, a lost job sent again, gets nothing).
    - `complete`: the metrics are written; only the ones the task has, and finite numbers.
    - `fail`: the predictions do not match the split (it is the data's fault): `failed` with the reason.
    - `release`: it could not, and it is not the data's fault (the storage was down): it waits again."""

    def __init__(
        self,
        evaluations: ModelEvaluationRepository,
        dataset_versions: DatasetVersionRepository,
        store: ObjectStore,
        *,
        max_attempts: int = 3,
        stale: timedelta = timedelta(minutes=30),
        signed_seconds: int = 3600,
    ) -> None:
        self._evaluations = evaluations
        self._dataset_versions = dataset_versions
        self._store = store
        self._max_attempts = max_attempts
        self._stale = stale
        self._signed_seconds = signed_seconds

    async def claim(self, evaluation_id: uuid.UUID) -> ToCompute | None:
        """Takes an evaluation in hand and says what to read. None when it is not up for the taking (done, being
        computed by another worker, unknown, still receiving its predictions, or given up after too many attempts)."""
        evaluation = await self._evaluations.claim(evaluation_id, datetime.now(UTC) - self._stale)
        if evaluation is None:
            return None
        if evaluation.attempts > self._max_attempts:
            await self._finish(evaluation, "The computation was interrupted too many times")
            return None
        try:
            return await self._to_compute(evaluation)
        except InvalidEvaluation as error:
            await self._finish(evaluation, str(error))
            return None

    async def _to_compute(self, evaluation: ModelEvaluation) -> ToCompute:
        if evaluation.dataset_id is None or evaluation.dataset_version is None or not evaluation.predictions_key:
            raise InvalidEvaluation("The dataset of this evaluation was deleted")
        version = await self._dataset_versions.get(evaluation.dataset_id, evaluation.dataset_version)
        if version is None:
            raise InvalidEvaluation("The version of the dataset of this evaluation was deleted")
        files = [f for f in await self._dataset_versions.files(version.id) if f.split == evaluation.split]
        if not files:
            raise InvalidEvaluation(f"The dataset has no split {evaluation.split}")
        urls = [await self._sign(f.storage_key) for f in files]
        return ToCompute(
            id=evaluation.id,
            task=evaluation.task,
            split=evaluation.split or "",
            target_column=evaluation.target_column or "",
            key_column=evaluation.key_column,
            prediction_column=evaluation.prediction_column,
            predictions=FileToRead(
                path=evaluation.predictions_key,
                url=await self._sign(evaluation.predictions_key),
                size_bytes=evaluation.predictions_size or 0,
            ),
            predictions_format=evaluation.predictions_format or "jsonl",
            truth=[
                FileToRead(path=f.path, url=url, size_bytes=f.size_bytes) for f, url in zip(files, urls, strict=True)
            ],
            metrics=computed_for(evaluation.task),
        )

    async def _sign(self, key: str) -> str:
        return await self._store.presign_get(key, self._signed_seconds, internal=True)

    async def complete(self, evaluation_id: uuid.UUID, results: dict[str, float], items: int) -> ModelEvaluation:
        """Writes the metrics the worker computed. Raises NotBeingProcessed when this evaluation was not given to a
        worker (done or given up meanwhile) and InvalidEvaluation for a metric the task does not have or a value that
        is not a finite number: the worker is not trusted more than a client."""
        evaluation = await self._running(evaluation_id)
        allowed = {metric.id for metric in metrics_for(evaluation.task)}
        if not results:
            raise InvalidEvaluation("A result needs at least one metric")
        for key, value in results.items():
            if key not in allowed:
                raise InvalidEvaluation(f"{key} is not a metric of {evaluation.task}")
            if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
                raise InvalidEvaluation(f"The value of {key} must be a finite number")
        evaluation.results = {key: float(value) for key, value in results.items()}
        # Not chosen yet: the first two metrics of the task that were computed (the main one first).
        evaluation.shown = [m.id for m in metrics_for(evaluation.task) if m.id in results][:2]
        evaluation.items = items
        evaluation.status, evaluation.error, evaluation.finished_at = DONE, None, datetime.now(UTC)
        await self._evaluations.commit()
        return evaluation

    async def fail(self, evaluation_id: uuid.UUID, reason: str) -> ModelEvaluation:
        evaluation = await self._running(evaluation_id)
        await self._finish(evaluation, reason)
        return evaluation

    async def release(self, evaluation_id: uuid.UUID) -> None:
        await self._evaluations.release(evaluation_id)

    async def waiting(self, limit: int = 200) -> list[uuid.UUID]:
        now = datetime.now(UTC)
        return await self._evaluations.waiting(older_than=now - GRACE, stale_before=now - self._stale, limit=limit)

    async def _running(self, evaluation_id: uuid.UUID) -> ModelEvaluation:
        evaluation = await self._evaluations.by_id(evaluation_id)
        if evaluation is None:
            raise EvaluationNotFound
        if evaluation.status != RUNNING:
            raise NotBeingProcessed
        return evaluation

    async def _finish(self, evaluation: ModelEvaluation, reason: str) -> None:
        evaluation.status, evaluation.error, evaluation.finished_at = FAILED, reason[:2000], datetime.now(UTC)
        await self._evaluations.commit()
        logger.warning("Evaluation %s failed: %s", evaluation.id, reason)
