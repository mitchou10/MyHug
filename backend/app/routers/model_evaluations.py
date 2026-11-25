import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.config import settings
from app.routers.deps import ActorDep, ModelEvaluationServiceDep
from app.schemas.dataset import PartOut, PartsOut, SignedPartOut
from app.schemas.evaluation import EvaluationOut, EvaluationStartIn, PartsRequest, ShownIn, UploadStateOut

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
    summary="Start an evaluation: the predictions of a model on a split of a dataset are about to be sent",
    description="Only the people who can edit the model. The platform computes the metrics, always: what is sent "
    "is the file of **predictions**, straight to the storage in parts (see `…/upload`); when it is all there, a "
    "worker computes. Nothing that is a metric can be sent.",
)
async def start_evaluation(
    owner: str, name: str, data: EvaluationStartIn, actor: ActorDep, service: ModelEvaluationServiceDep
) -> EvaluationOut:
    fields = data.model_dump(exclude={"inference"})
    inference = data.inference.model_dump(exclude_none=True) if data.inference else None
    started = await service.start(actor, owner, name, **fields, inference=inference or None)
    return EvaluationOut.from_view(started.view)


@router.get("/{evaluation_id}", summary="One evaluation")
async def get_evaluation(
    owner: str, name: str, evaluation_id: uuid.UUID, actor: ActorDep, service: ModelEvaluationServiceDep
) -> EvaluationOut:
    return EvaluationOut.from_view(await service.get(actor, owner, name, evaluation_id))


# ---- the predictions go to the storage, in parts, straight from the program


@router.get("/{evaluation_id}/upload", summary="Where the predictions are going, and with `parts` what arrived")
async def get_upload(
    owner: str,
    name: str,
    evaluation_id: uuid.UUID,
    actor: ActorDep,
    service: ModelEvaluationServiceDep,
    parts: Annotated[bool, Query(description="Also what reached the storage, to resume")] = False,
) -> UploadStateOut:
    state = await service.upload(actor, owner, name, evaluation_id, parts=parts)
    e = state.evaluation
    received = [PartOut(number=p.number, size=p.size) for p in state.received] if state.received is not None else None
    return UploadStateOut(
        status=e.status,
        size_bytes=e.predictions_size,
        part_size=e.part_size,
        parts_count=e.parts_count,
        expires_at=e.expires_at,
        received=received,
    )


@router.post("/{evaluation_id}/upload/parts", summary="Signed addresses to send parts of the predictions to")
async def sign_parts(
    owner: str,
    name: str,
    evaluation_id: uuid.UUID,
    data: PartsRequest,
    actor: ActorDep,
    service: ModelEvaluationServiceDep,
) -> PartsOut:
    signed = await service.part_urls(actor, owner, name, evaluation_id, data.numbers)
    return PartsOut(
        parts=[SignedPartOut(number=n, url=url) for n, url in signed], expires_in=settings.SIGNED_ADDRESS_SECONDS
    )


@router.post("/{evaluation_id}/upload/complete", summary="Put the parts together: a worker computes the metrics")
async def complete_upload(
    owner: str, name: str, evaluation_id: uuid.UUID, actor: ActorDep, service: ModelEvaluationServiceDep
) -> EvaluationOut:
    return EvaluationOut.from_view(await service.complete(actor, owner, name, evaluation_id))


# ---- choosing and deleting


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


@router.delete(
    "/{evaluation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an evaluation, or give up the predictions that were being sent",
)
async def delete_evaluation(
    owner: str, name: str, evaluation_id: uuid.UUID, actor: ActorDep, service: ModelEvaluationServiceDep
) -> Response:
    await service.delete(actor, owner, name, evaluation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
