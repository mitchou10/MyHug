import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.metrics import metrics_for
from app.models import ModelEvaluation
from app.models.model_evaluation import DONE, SUBMITTED
from app.repositories.model_evaluations import ModelEvaluationRepository
from app.repositories.model_versions import ModelVersionRepository
from app.services.actor import Actor
from app.services.dataset_access import DatasetAccess
from app.services.errors import DatasetNotFound, EvaluationNotFound, InvalidEvaluation, ModelVersionNotFound
from app.services.model_access import EDITORS, ModelAccess

MAX_METRICS = 50


@dataclass(frozen=True)
class EvaluationView:
    """An evaluation as one person sees it: a person who cannot edit the model sees only the metrics that were chosen
    to be shown, and the address of the dataset only if they may read it."""

    evaluation: ModelEvaluation
    results: dict[str, float]
    hidden: int
    dataset: str | None
    can_edit: bool


class ModelEvaluationService:
    def __init__(
        self,
        access: ModelAccess,
        evaluations: ModelEvaluationRepository,
        versions: ModelVersionRepository,
        dataset_access: DatasetAccess,
    ) -> None:
        self._access = access
        self._evaluations = evaluations
        self._versions = versions
        self._dataset_access = dataset_access

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

    async def submit(
        self,
        actor: Actor,
        owner: str,
        name: str,
        *,
        version: int,
        task: str,
        results: dict[str, float],
        shown: list[str] | None,
        dataset: str | None,
        dataset_version: int | None,
        split: str | None,
        input_column: str | None,
        target_column: str | None,
        items: int | None,
        note: str,
    ) -> EvaluationView:
        """Takes a result somebody computed elsewhere. Only the people who can edit the model may send one, and it is
        always kept as `submitted`: nothing says the platform measured it."""
        model = await self._access.get_editable(actor, owner, name)
        found = await self._versions.get(model.id, version)
        if found is None:
            raise ModelVersionNotFound
        if task not in model.tasks:
            raise InvalidEvaluation(f"This model does not do {task}: it does {', '.join(model.tasks)}")
        results = _checked_results(task, results)
        # Not chosen: the first two metrics of the task that the result has (the main one, when it has it).
        chosen = [m.id for m in metrics_for(task) if m.id in results][:2] if shown is None else shown
        chosen = list(dict.fromkeys(chosen))
        if unknown := [m for m in chosen if m not in results]:
            raise InvalidEvaluation(f"{unknown[0]} cannot be shown: the result has no such metric")
        dataset_id, address = await self._dataset(actor, dataset)
        evaluation = ModelEvaluation(
            model_id=model.id,
            version_id=found.id,
            version_number=found.number,
            task=task,
            dataset_id=dataset_id,
            dataset_address=address,
            dataset_version=dataset_version if address else None,
            split=split,
            input_column=input_column,
            target_column=target_column,
            items=items,
            source=SUBMITTED,
            status=DONE,
            results=results,
            shown=[m for m in chosen if m in results],
            note=note,
            created_by=actor.user_id,
            created_by_username=actor.username,
            finished_at=datetime.now(UTC),
        )
        self._evaluations.add(evaluation)
        await self._evaluations.commit()
        return (await self._views(actor, "owner", [evaluation]))[0]

    async def _dataset(self, actor: Actor, address: str | None) -> tuple[uuid.UUID | None, str | None]:
        """The dataset a result says it is about. One the person cannot read is refused as one that does not exist, so
        that this cannot be used to find out which private datasets there are."""
        if address is None:
            return None, None
        owner, _, name = address.partition("/")
        try:
            dataset, _ = await self._dataset_access.get_readable(actor, owner, name)
        except DatasetNotFound:
            raise InvalidEvaluation(f"No dataset {address}") from None
        return dataset.id, f"{dataset.owner}/{dataset.name}"

    async def set_shown(
        self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID, shown: list[str]
    ) -> EvaluationView:
        model = await self._access.get_editable(actor, owner, name)
        evaluation = await self._evaluations.get(model.id, evaluation_id)
        if evaluation is None:
            raise EvaluationNotFound
        chosen = list(dict.fromkeys(shown))
        if unknown := [m for m in chosen if m not in evaluation.results]:
            raise InvalidEvaluation(f"{unknown[0]} cannot be shown: the result has no such metric")
        evaluation.shown = chosen
        await self._evaluations.commit()
        return (await self._views(actor, "owner", [evaluation]))[0]

    async def delete(self, actor: Actor, owner: str, name: str, evaluation_id: uuid.UUID) -> None:
        model = await self._access.get_editable(actor, owner, name)
        evaluation = await self._evaluations.get(model.id, evaluation_id)
        if evaluation is None:
            raise EvaluationNotFound
        await self._evaluations.delete(evaluation)
        await self._evaluations.commit()


def _checked_results(task: str, results: dict[str, Any]) -> dict[str, float]:
    """The metrics of a result: the ones the task has, each a finite number."""
    if not results:
        raise InvalidEvaluation("A result needs at least one metric")
    if len(results) > MAX_METRICS:
        raise InvalidEvaluation(f"A result has at most {MAX_METRICS} metrics")
    allowed = {metric.id for metric in metrics_for(task)}
    checked: dict[str, float] = {}
    for key, value in results.items():
        if key not in allowed:
            raise InvalidEvaluation(f"{key} is not a metric of {task}: {', '.join(sorted(allowed))}")
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise InvalidEvaluation(f"The value of {key} must be a finite number")
        checked[key] = float(value)
    return checked
