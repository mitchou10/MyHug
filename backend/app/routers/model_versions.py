from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import RedirectResponse

from app.routers.deps import ActorDep, ModelVersionServiceDep
from app.schemas import CodeVersionIn, ModelFileOut, ModelVersionDetailOut, ModelVersionOut

router = APIRouter(prefix="/api/models/{owner}/{name}", tags=["model versions"])


@router.post(
    "/versions",
    status_code=status.HTTP_201_CREATED,
    summary="A version that is only a link to the code (the files come with an upload)",
)
async def create_code_version(
    owner: str, name: str, data: CodeVersionIn, actor: ActorDep, service: ModelVersionServiceDep
) -> ModelVersionOut:
    version = await service.create_code_version(actor, owner, name, code=data.code.model_dump(), message=data.message)
    view, _ = await service.get(actor, owner, name, version.number)
    return ModelVersionOut.from_view(view)


@router.get("/versions", summary="The versions of a model, the newest first")
async def list_versions(
    owner: str, name: str, actor: ActorDep, service: ModelVersionServiceDep
) -> list[ModelVersionOut]:
    return [ModelVersionOut.from_view(view) for view in await service.history(actor, owner, name)]


@router.get("/versions/{number}", summary="One version, with its files")
async def get_version(
    owner: str, name: str, number: int, actor: ActorDep, service: ModelVersionServiceDep
) -> ModelVersionDetailOut:
    view, files = await service.get(actor, owner, name, number)
    return ModelVersionDetailOut.from_files(view, files)


@router.delete(
    "/versions/{number}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a version, in MLflow too (the files that another version holds are kept)",
)
async def delete_version(
    owner: str, name: str, number: int, actor: ActorDep, service: ModelVersionServiceDep
) -> Response:
    await service.delete(actor, owner, name, number)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/files", summary="The files of a version (the latest by default)")
async def list_files(
    owner: str,
    name: str,
    actor: ActorDep,
    service: ModelVersionServiceDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> list[ModelFileOut]:
    _, files = await service.get(actor, owner, name, version)
    return [ModelFileOut.model_validate(file) for file in files]


@router.get(
    "/files/{path:path}",
    summary="Download a file: it answers with a redirection to a signed address of the storage",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
async def download_file(
    owner: str,
    name: str,
    path: str,
    actor: ActorDep,
    service: ModelVersionServiceDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> RedirectResponse:
    return RedirectResponse(
        await service.download(actor, owner, name, path, version), status_code=status.HTTP_302_FOUND
    )
