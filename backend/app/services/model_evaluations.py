import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.jobs import Jobs
from app.metrics import MEASURABLE
from app.models import ModelEvaluation
from app.models.model_evaluation import PENDING, PREDICTIONS, UPLOADING
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.model_evaluations import ModelEvaluationRepository
from app.repositories.model_versions import ModelVersionRepository
from app.services.actor import Actor
from app.services.dataset_access import DatasetAccess
from app.services.dataset_uploads import part_size_for
from app.services.dataset_versions import splits_of
from app.services.errors import (
    DatasetNotFound,
    EvaluationNotFound,
    InvalidEvaluation,
    ModelVersionNotFound,
    TooManyEvaluations,
    UploadClosed,
    UploadIncomplete,
)
from app.services.model_access import EDITORS, ModelAccess
from app.storage import ObjectStore, PartInfo


@dataclass(frozen=True)
class EvaluationView:
    """An evaluation as one person sees it: a person who cannot edit the model sees only the metrics that were chosen
    to be shown, and the address of the dataset only if they may read it."""

    evaluation: ModelEvaluation
    results: dict[str, float]
    hidden: int
    dataset: str | None
    can_edit: bool


@dataclass(frozen=True)
class StartedEvaluation:
    view: EvaluationView
    # How the predictions go to the storage: their parts, and the time left to send them.
    part_size: int
    parts_count: int


@dataclass(frozen=True)
class PredictionsUpload:
    evaluation: ModelEvaluation
    # What reached the storage so far: only when asked (it is a call to the storage).
    received: list[PartInfo] | None


def predictions_key(evaluation_id: uuid.UUID, format: str) -> str:
    return f"evaluations/{evaluation_id}/predictions.{format}"


class ModelEvaluationService:
    """The evaluations of the versions of a model.

    The platform computes the metrics, always (a worker does, from predictions). A person who can edit the model
    starts an evaluation and sends the predictions of their model on a split of a dataset, as a file that goes straight
    to the storage in parts; when it is all there a worker computes. Nothing a person sends is ever a metric."""

    def __init__(
        self,
        access: ModelAccess,
        evaluations: ModelEvaluationRepository,
        versions: ModelVersionRepository,
        dataset_access: DatasetAccess,
        dataset_versions: DatasetVersionRepository,
        store: ObjectStore,
        jobs: Jobs,
        *,
        max_bytes: int,
        part_bytes: int,
        signed_seconds: int,
        session: timedelta,
        max_open: int,
    ) -> None:
        self._access = access
        self._evaluations = evaluations
        self._versions = versions
        self._dataset_access = dataset_access
        self._dataset_versions = dataset_versions
        self._store = store
        self._jobs = jobs
        self._max_bytes = max_bytes
        self._part_bytes = part_bytes
        self._signed_seconds = signed_seconds
        self._session = session
        self._max_open = max_open

    # ---- reading

    async def _views(self, actor: Actor, role: str | None, evaluations: list[ModelEvaluation]) -> list[EvaluationView]:
        editor = role in EDITORS
        readable = await self._evaluations.readable_datasets(
            {e.dataset_id for e in evaluations if e.dataset_id}, actor.user_id, actor.is_admin
        )
        views = []
        for evaluation in evaluations:
            shown = {k: v for k, v in evaluation.results.items() if editor or k in evaluation.shown}
            dataset = None
            if evaluation.dataset_address is not None:
                # A dataset that was deleted is no longer there to ask: only the people who edit the model are told its
                # address, as the others may never have been allowed to read it.
                allowed = editor if evaluation.dataset_id is None else evaluation.dataset_id in readable
                dataset = evaluation.dataset_address if allowed else None
            views.append(EvaluationView(evaluation, shown, len(evaluation.results) - len(shown), dataset, editor))
        return views

    async def page(
        self, actor: Actor, owner: str, name: str, *, task: str | None, version: int | None, limit: int, offset: int
    ) -> list[EvaluationView]:
        model, role = await self._access.get_readable(actor, owner, name)
        found = await self._evaluations.page(model.id, task=task, version=version, limit=limit, offset=offset)
        return await self._views(actor, role, found)

    async def get(self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID) -> EvaluationView:
        model, role = await self._access.get_readable(actor, owner, name)
        evaluation = await self._evaluations.get(model.id, evaluation_id)
        if evaluation is None:
            raise EvaluationNotFound
        return (await self._views(actor, role, [evaluation]))[0]

    # ---- starting

    async def start(
        self,
        actor: Actor,
        owner: str,
        name: str,
        *,
        version: int,
        task: str,
        dataset: str,
        dataset_version: int | None,
        split: str,
        target_column: str,
        key_column: str | None,
        input_column: str | None,
        prediction_column: str,
        format: str,
        size: int,
        note: str,
        inference: dict | None = None,
    ) -> StartedEvaluation:
        """Starts an evaluation and opens the way for its predictions. Everything that can be known to be wrong is
        said here, before anything is stored: the version, the task, the dataset, its split and its columns."""
        model = await self._access.get_editable(actor, owner, name)
        found = await self._versions.get(model.id, version)
        if found is None:
            raise ModelVersionNotFound
        if task not in model.tasks:
            raise InvalidEvaluation(f"This model does not do {task}: it does {', '.join(model.tasks)}")
        if task not in MEASURABLE:
            raise InvalidEvaluation(f"The platform does not compute the metrics of {task} yet")
        if size <= 0:
            raise InvalidEvaluation("The predictions are empty")
        if size > self._max_bytes:
            raise InvalidEvaluation(f"The predictions are over {self._max_bytes // 1024**2} MiB")
        if await self._evaluations.count_open(model.id) >= self._max_open:
            raise TooManyEvaluations
        truth = await self._ground_truth(actor, dataset, dataset_version, split, target_column, key_column)

        evaluation_id = uuid.uuid4()
        key = predictions_key(evaluation_id, format)
        part = part_size_for(size, self._part_bytes)
        multipart_id = await self._store.create_multipart(key, CONTENT_TYPES[format])
        evaluation = ModelEvaluation(
            id=evaluation_id,
            model_id=model.id,
            version_id=found.id,
            version_number=found.number,
            task=task,
            dataset_id=truth.dataset_id,
            dataset_address=truth.address,
            dataset_version=truth.version,
            split=split,
            input_column=input_column,
            target_column=target_column,
            key_column=key_column,
            prediction_column=prediction_column,
            source=PREDICTIONS,
            status=UPLOADING,
            predictions_key=key,
            predictions_format=format,
            predictions_size=size,
            multipart_id=multipart_id,
            part_size=part,
            parts_count=math.ceil(size / part),
            expires_at=datetime.now(UTC) + self._session,
            note=note,
            inference=inference,
            created_by=actor.user_id,
            created_by_username=actor.username,
        )
        try:
            self._evaluations.add(evaluation)
            await self._evaluations.commit()
        except Exception:
            await self._store.abort_multipart(key, multipart_id)
            raise
        view = (await self._views(actor, "owner", [evaluation]))[0]
        return StartedEvaluation(view, part, evaluation.parts_count or 0)

    async def _ground_truth(
        self, actor: Actor, address: str, number: int | None, split: str, target: str, key: str | None
    ) -> "Truth":
        """The dataset, its version, its split and the columns the metrics are computed against. One that cannot be read
        is refused as one that does not exist, so that this cannot be used to find which private datasets there are."""
        owner, _, name = address.partition("/")
        try:
            dataset, _ = await self._dataset_access.get_readable(actor, owner, name)
        except DatasetNotFound:
            raise InvalidEvaluation(f"No dataset {address}") from None
        version = (
            await self._dataset_versions.get(dataset.id, number)
            if number is not None
            else await self._dataset_versions.latest(dataset.id)
        )
        if version is None:
            raise InvalidEvaluation(f"No version {number} of {address}" if number else f"{address} has no version yet")
        splits = [s.name for s in splits_of(await self._dataset_versions.files(version.id))]
        if split not in splits:
            raise InvalidEvaluation(f"{address} has no split {split}: it has {', '.join(splits) or 'none'}")
        columns = {c["name"] for c in version.columns}
        for column in (target, key):
            if column is not None and column not in columns:
                raise InvalidEvaluation(f"{address} has no column {column}")
        return Truth(dataset.id, f"{dataset.owner}/{dataset.name}", version.number)

    # ---- the predictions go to the storage

    async def _uploading(self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID) -> ModelEvaluation:
        model = await self._access.get_editable(actor, owner, name)
        evaluation = await self._evaluations.get(model.id, evaluation_id)
        if evaluation is None:
            raise EvaluationNotFound
        return evaluation

    async def upload(
        self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID, *, parts: bool
    ) -> PredictionsUpload:
        """Where the upload is, and with `parts` what reached the storage (to go on after an interruption)."""
        evaluation = await self._uploading(actor, owner, name, evaluation_id)
        received = None
        if parts and evaluation.status == UPLOADING and evaluation.predictions_key and evaluation.multipart_id:
            received = await self._store.list_parts(evaluation.predictions_key, evaluation.multipart_id)
        return PredictionsUpload(evaluation, received)

    async def part_urls(
        self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID, numbers: list[int]
    ) -> list[tuple[int, str]]:
        evaluation = await self._uploading(actor, owner, name, evaluation_id)
        if evaluation.status != UPLOADING or not evaluation.multipart_id or not evaluation.predictions_key:
            raise UploadClosed
        count = evaluation.parts_count or 0
        if any(not 1 <= number <= count for number in numbers):
            raise UploadIncomplete(f"The predictions have {count} parts: ask for a number from 1 to {count}")
        key, multipart_id = evaluation.predictions_key, evaluation.multipart_id
        return [(n, await self._store.presign_part(key, multipart_id, n, self._signed_seconds)) for n in numbers]

    async def complete(self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID) -> EvaluationView:
        """Puts the parts together and queues the computation. Doing it again after it worked changes nothing."""
        evaluation = await self._uploading(actor, owner, name, evaluation_id)
        if evaluation.status != UPLOADING:
            return (await self._views(actor, "owner", [evaluation]))[0]
        if datetime.now(UTC) >= (evaluation.expires_at or datetime.now(UTC)):
            raise UploadClosed
        assert evaluation.predictions_key and evaluation.multipart_id  # an upload that is going on has them
        key, multipart_id = evaluation.predictions_key, evaluation.multipart_id
        parts = await self._checked_parts(evaluation, key, multipart_id)
        await self._store.complete_multipart(key, multipart_id, parts)
        info = await self._store.head(key)
        if info is None or info.size != evaluation.predictions_size:
            await self._store.delete(key)
            raise UploadIncomplete(
                f"The predictions are {info.size if info else 0} bytes, not {evaluation.predictions_size}"
            )
        evaluation.status, evaluation.multipart_id, evaluation.expires_at = PENDING, None, None
        await self._evaluations.commit()
        await self._jobs.evaluate(evaluation.id)
        return (await self._views(actor, "owner", [evaluation]))[0]

    async def _checked_parts(self, evaluation: ModelEvaluation, key: str, multipart_id: str) -> list[PartInfo]:
        """The parts, if they are all there and the size they were announced."""
        found = {part.number: part for part in await self._store.list_parts(key, multipart_id)}
        count, part_size, total = (
            evaluation.parts_count or 0,
            evaluation.part_size or 0,
            evaluation.predictions_size or 0,
        )
        for number in range(1, count + 1):
            expected = part_size if number < count else total - part_size * (count - 1)
            part = found.get(number)
            if part is None:
                raise UploadIncomplete(f"Part {number} of the predictions is missing")
            if part.size != expected:
                raise UploadIncomplete(f"Part {number} of the predictions has {part.size} bytes, not {expected}")
        return [found[number] for number in range(1, count + 1)]

    # ---- changing, deleting, giving up

    async def set_shown(
        self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID, shown: list[str]
    ) -> EvaluationView:
        evaluation = await self._uploading(actor, owner, name, evaluation_id)
        chosen = list(dict.fromkeys(shown))
        if unknown := [m for m in chosen if m not in evaluation.results]:
            raise InvalidEvaluation(f"{unknown[0]} cannot be shown: the result has no such metric")
        evaluation.shown = chosen
        await self._evaluations.commit()
        return (await self._views(actor, "owner", [evaluation]))[0]

    async def delete(self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID) -> None:
        """Deletes an evaluation, and what it kept in the storage: its predictions, or the parts that arrived."""
        evaluation = await self._uploading(actor, owner, name, evaluation_id)
        await self._free(evaluation)
        await self._evaluations.delete(evaluation)
        await self._evaluations.commit()

    async def expire_stale(self, now: datetime | None = None) -> int:
        """Gives up the evaluations whose predictions did not arrive in time, and frees what they had received."""
        stale = await self._evaluations.uploading_until(now or datetime.now(UTC))
        for evaluation in stale:
            await self._free(evaluation)
            await self._evaluations.delete(evaluation)
        await self._evaluations.commit()
        return len(stale)

    async def _free(self, evaluation: ModelEvaluation) -> None:
        if not evaluation.predictions_key:
            return
        if evaluation.multipart_id:
            await self._store.abort_multipart(evaluation.predictions_key, evaluation.multipart_id)
        await self._store.delete(evaluation.predictions_key)


@dataclass(frozen=True)
class Truth:
    dataset_id: uuid.UUID
    address: str
    version: int


CONTENT_TYPES = {
    "jsonl": "application/x-ndjson",
    "csv": "text/csv",
    "parquet": "application/vnd.apache.parquet",
}
