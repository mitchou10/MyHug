from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from app.config import settings
from app.routers.deps import ActorDep, DatasetServiceDep, DatasetVersionServiceDep
from app.routers.uploads import read_dataset_files
from app.schemas import (
    DatasetChange,
    DatasetIn,
    DatasetOut,
    DatasetSummaryOut,
    FileOut,
    LikeOut,
    Page,
    RowsOut,
    VersionOut,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("", summary="The datasets I can see: the public ones, mine, and those shared with me")
async def list_datasets(
    actor: ActorDep,
    service: DatasetServiceDep,
    q: Annotated[
        str | None, Query(max_length=200, description="Looked for in the address, the description, the tags")
    ] = None,
    modality: Literal["text", "image", "audio", "video", "tabular", "timeseries"] | None = None,
    sort: Literal["downloads", "likes", "updated"] = "downloads",
    limit: Annotated[int, Query(ge=1, le=settings.PAGE_SIZE_MAX)] = 12,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DatasetSummaryOut]:
    rows, total = await service.list_page(actor, query=q, modality=modality, sort=sort, limit=limit, offset=offset)
    return Page(items=[DatasetSummaryOut.from_row(row) for row in rows], total=total, limit=limit, offset=offset)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a dataset, in my own name")
async def create_dataset(data: DatasetIn, actor: ActorDep, service: DatasetServiceDep) -> DatasetOut:
    return DatasetOut.from_view(await service.create(actor, **data.model_dump()))


@router.get("/{owner}/{name}", summary="One dataset")
async def get_dataset(owner: str, name: str, actor: ActorDep, service: DatasetServiceDep) -> DatasetOut:
    return DatasetOut.from_view(await service.get(actor, owner, name))


@router.patch("/{owner}/{name}", summary="Change a dataset: its creator, its maintainers and the admins")
async def change_dataset(
    owner: str, name: str, data: DatasetChange, actor: ActorDep, service: DatasetServiceDep
) -> DatasetOut:
    return DatasetOut.from_view(await service.update(actor, owner, name, data.model_dump(exclude_unset=True)))


@router.delete("/{owner}/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a dataset")
async def delete_dataset(owner: str, name: str, actor: ActorDep, service: DatasetServiceDep) -> Response:
    await service.delete(actor, owner, name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{owner}/{name}/like", summary="Like a dataset (doing it again changes nothing)")
async def like_dataset(owner: str, name: str, actor: ActorDep, service: DatasetServiceDep) -> LikeOut:
    liked, likes = await service.like(actor, owner, name)
    return LikeOut(liked=liked, likes=likes)


@router.delete("/{owner}/{name}/like", summary="Stop liking a dataset")
async def unlike_dataset(owner: str, name: str, actor: ActorDep, service: DatasetServiceDep) -> LikeOut:
    liked, likes = await service.unlike(actor, owner, name)
    return LikeOut(liked=liked, likes=likes)


# ---- the files: each change makes a new version


@router.post(
    "/{owner}/{name}/versions", status_code=status.HTTP_201_CREATED, summary="Add or remove files: a new version"
)
async def create_version(
    owner: str,
    name: str,
    actor: ActorDep,
    service: DatasetVersionServiceDep,
    files: Annotated[list[UploadFile] | None, File()] = None,
    paths: Annotated[list[str] | None, Form(description="Where each file goes, in the order of the files")] = None,
    remove: Annotated[list[str] | None, Form(description="Paths of the files to take out")] = None,
    message: Annotated[str, Form(max_length=500)] = "",
) -> VersionOut:
    uploads = await read_dataset_files(files, paths)
    version = await service.create(actor, owner, name, uploads=uploads, remove=remove or [], message=message)
    return VersionOut.model_validate(version)


@router.get("/{owner}/{name}/versions", summary="The versions of a dataset, the newest first")
async def list_versions(owner: str, name: str, actor: ActorDep, service: DatasetVersionServiceDep) -> list[VersionOut]:
    return [VersionOut.model_validate(version) for version in await service.history(actor, owner, name)]


@router.get("/{owner}/{name}/files", summary="The files of a version (the latest by default)")
async def list_files(
    owner: str,
    name: str,
    actor: ActorDep,
    service: DatasetVersionServiceDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> list[FileOut]:
    _, files = await service.files(actor, owner, name, version)
    return [FileOut.model_validate(file) for file in files]


@router.get(
    "/{owner}/{name}/files/{path:path}",
    summary="Download a file: it answers with a redirection to a signed address of the storage",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
async def download_file(
    owner: str,
    name: str,
    path: str,
    actor: ActorDep,
    service: DatasetVersionServiceDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> RedirectResponse:
    return RedirectResponse(
        await service.download(actor, owner, name, path, version), status_code=status.HTTP_302_FOUND
    )


@router.get("/{owner}/{name}/rows", summary="The rows of a split, for the preview")
async def list_rows(
    owner: str,
    name: str,
    actor: ActorDep,
    service: DatasetVersionServiceDep,
    split: Annotated[str | None, Query(max_length=20, description="`train` if there is one, else the first")] = None,
    version: Annotated[int | None, Query(ge=1)] = None,
    q: Annotated[str | None, Query(max_length=200, description="Keeps the rows that contain it")] = None,
    limit: Annotated[int, Query(ge=1, le=settings.PAGE_SIZE_MAX * 2)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RowsOut:
    page = await service.rows(actor, owner, name, split=split, number=version, offset=offset, limit=limit, query=q)
    return RowsOut.from_page(page, limit, offset)
