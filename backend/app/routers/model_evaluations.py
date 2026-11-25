import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.config import settings
from app.routers.deps import ActorDep, ModelEvaluationServiceDep
from app.schemas.evaluation import EvaluationIn, EvaluationOut, ShownIn

router = APIRouter(prefix="/api/models/{owner}/{name}/evaluations", tags=["model evaluations"])


@router.get("", summary="The evaluations of a model, the newest first")
async def list_evaluations(
    owner: str,
    name: str,
    actor: ActorDep,
    service: ModelEvaluationServiceDep,
    task: Annotated[str | None, Query(max_length=40)] = None,
    version: Annotated[int | None, Query(ge=1, description="The number of a version of the model")] = None,
    limit: Annotated[int, Query(ge=1, le=settings.PAGE_SIZE_MAX)] = settings.PAGE_SIZE_MAX,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EvaluationOut]:
    views = await service.page(actor, owner, name, task=task, version=version, limit=limit, offset=offset)
    return [EvaluationOut.from_view(view) for view in views]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Send the result of an evaluation computed elsewhere (the people who can edit the model)",
    description="It is kept and shown as **submitted**: nothing says the platform measured it.",
)
async def submit_evaluation(
    owner: str, name: str, data: EvaluationIn, actor: ActorDep, service: ModelEvaluationServiceDep
) -> EvaluationOut:
    view = await service.submit(actor, owner, name, **data.model_dump())
    return EvaluationOut.from_view(view)


@router.get("/{evaluation_id}", summary="One evaluation")
async def get_evaluation(
    owner: str, name: str, evaluation_id: uuid.UUID, actor: ActorDep, service: ModelEvaluationServiceDep
) -> EvaluationOut:
    return EvaluationOut.from_view(await service.get(actor, owner, name, evaluation_id))


@router.put("/{evaluation_id}/shown", summary="Choose the metrics the others see")
async def set_shown(
    owner: str,
    name: str,
    evaluation_id: uuid.UUID,
    data: ShownIn,
    actor: ActorDep,
    service: ModelEvaluationServiceDep,
) -> EvaluationOut:
    return EvaluationOut.from_view(await service.set_shown(actor, owner, name, evaluation_id, data.shown))


@router.delete("/{evaluation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an evaluation")
async def delete_evaluation(
    owner: str, name: str, evaluation_id: uuid.UUID, actor: ActorDep, service: ModelEvaluationServiceDep
) -> Response:
    await service.delete(actor, owner, name, evaluation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
