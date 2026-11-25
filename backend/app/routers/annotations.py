import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.config import settings
from app.routers.deps import ActorDep, AnnotationServiceDep
from app.schemas.annotation import (
    AnswerIn,
    AnswerOut,
    LabelIn,
    LabelOut,
    LabelPatch,
    ProgressOut,
    RowsOut,
    TaskIn,
    TaskOut,
    TaskPatch,
)

router = APIRouter(tags=["annotation"])


@router.get("/api/datasets/{owner}/{name}/tasks", summary="The tasks of annotation of a dataset")
async def list_tasks(owner: str, name: str, actor: ActorDep, service: AnnotationServiceDep) -> list[TaskOut]:
    return [TaskOut.from_view(view) for view in await service.tasks(actor, owner, name)]


@router.post(
    "/api/datasets/{owner}/{name}/tasks",
    status_code=status.HTTP_201_CREATED,
    summary="Make a task of annotation: a text to classify in each row of the dataset",
    description="Only the people who can edit the dataset. The task follows the dataset: it reads the rows of its "
    "latest version.",
)
async def create_task(owner: str, name: str, data: TaskIn, actor: ActorDep, service: AnnotationServiceDep) -> TaskOut:
    view = await service.create(
        actor,
        owner,
        name,
        task_name=data.name,
        type=data.type,
        text_column=data.text_column,
        labels=[(label.name, label.description) for label in data.labels],
    )
    return TaskOut.from_view(view)


@router.get("/api/tasks/{task_id}", summary="One task, with its labels")
async def get_task(task_id: uuid.UUID, actor: ActorDep, service: AnnotationServiceDep) -> TaskOut:
    return TaskOut.from_view(await service.get(actor, task_id))


@router.patch("/api/tasks/{task_id}", summary="Rename a task, close it or open it again")
async def update_task(task_id: uuid.UUID, data: TaskPatch, actor: ActorDep, service: AnnotationServiceDep) -> TaskOut:
    view = await service.update(actor, task_id, name=data.name, status=data.status)
    return TaskOut.from_view(view)


@router.delete(
    "/api/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task, its labels and all its answers",
)
async def delete_task(task_id: uuid.UUID, actor: ActorDep, service: AnnotationServiceDep) -> Response:
    await service.delete(actor, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- labels


@router.post("/api/tasks/{task_id}/labels", status_code=status.HTTP_201_CREATED, summary="Add a label")
async def add_label(task_id: uuid.UUID, data: LabelIn, actor: ActorDep, service: AnnotationServiceDep) -> LabelOut:
    return LabelOut.of(await service.add_label(actor, task_id, name=data.name, description=data.description))


@router.patch(
    "/api/tasks/{task_id}/labels/{label_id}",
    summary="Rename or describe a label: the answers that use it follow, nothing is lost",
)
async def update_label(
    task_id: uuid.UUID, label_id: uuid.UUID, data: LabelPatch, actor: ActorDep, service: AnnotationServiceDep
) -> LabelOut:
    label = await service.update_label(actor, task_id, label_id, name=data.name, description=data.description)
    return LabelOut.of(label)


@router.delete(
    "/api/tasks/{task_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop offering a label: the answers that use it keep it",
)
async def delete_label(
    task_id: uuid.UUID, label_id: uuid.UUID, actor: ActorDep, service: AnnotationServiceDep
) -> Response:
    await service.delete_label(actor, task_id, label_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- rows and answers


@router.get("/api/tasks/{task_id}/rows", summary="The rows to annotate, with my answer to each")
async def list_rows(
    task_id: uuid.UUID,
    actor: ActorDep,
    service: AnnotationServiceDep,
    split: Annotated[str | None, Query(max_length=50)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=settings.PAGE_SIZE_MAX)] = 20,
) -> RowsOut:
    return RowsOut.of(await service.rows(actor, task_id, split=split, offset=offset, limit=limit))


@router.put(
    "/api/tasks/{task_id}/rows/{split}/{row_index}/annotation",
    summary="Answer a row (or change my answer): the same call twice changes nothing",
    description="One answer per person and per row. The answer keeps the version of the dataset it was given on.",
)
async def put_answer(
    task_id: uuid.UUID,
    split: str,
    row_index: int,
    data: AnswerIn,
    actor: ActorDep,
    service: AnnotationServiceDep,
) -> AnswerOut:
    answer = await service.answer(
        actor, task_id, split, row_index, label_id=data.label_id, reason=data.reason, status=data.status
    )
    return AnswerOut.of(answer)


@router.delete(
    "/api/tasks/{task_id}/rows/{split}/{row_index}/annotation",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Take back my answer to a row",
)
async def delete_answer(
    task_id: uuid.UUID, split: str, row_index: int, actor: ActorDep, service: AnnotationServiceDep
) -> Response:
    await service.take_back(actor, task_id, split, row_index)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/tasks/{task_id}/progress", summary="How far the annotation is")
async def get_progress(task_id: uuid.UUID, actor: ActorDep, service: AnnotationServiceDep) -> ProgressOut:
    return ProgressOut.of(await service.progress(actor, task_id))
