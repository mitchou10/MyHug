from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from app.config import settings
from app.routers.deps import ActorDep, ModelMemberServiceDep, ModelServiceDep
from app.schemas import LikeOut, MemberIn, MemberOut, ModelChange, ModelIn, ModelOut, ModelSummaryOut, Page

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", summary="The models I can see: the public ones, mine, and those shared with me")
async def list_models(
    actor: ActorDep,
    service: ModelServiceDep,
    q: Annotated[
        str | None, Query(max_length=200, description="Looked for in the address, the description, the tags")
    ] = None,
    owner: Annotated[str | None, Query(max_length=100)] = None,
    task: Annotated[str | None, Query(max_length=40, description="A task the model can do")] = None,
    modality: Annotated[
        Literal["text", "image", "audio", "video", "tabular", "timeseries"] | None,
        Query(description="A kind of data the model takes"),
    ] = None,
    library: Annotated[str | None, Query(max_length=50)] = None,
    language: Annotated[str | None, Query(max_length=50)] = None,
    license: Annotated[str | None, Query(max_length=100)] = None,
    tags: Annotated[list[str] | None, Query(description="All of them must be on the model")] = None,
    sort: Literal["downloads", "likes", "updated"] = "downloads",
    limit: Annotated[int, Query(ge=1, le=settings.PAGE_SIZE_MAX)] = 12,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ModelSummaryOut]:
    rows, total = await service.list_page(
        actor,
        query=q,
        owner=owner,
        task=task,
        modality=modality,
        library=library,
        language=language,
        license=license,
        tags=[tag.strip().lower() for tag in tags or []],
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return Page(items=[ModelSummaryOut.from_row(row) for row in rows], total=total, limit=limit, offset=offset)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a model, in my own name")
async def create_model(data: ModelIn, actor: ActorDep, service: ModelServiceDep) -> ModelOut:
    return ModelOut.from_view(await service.create(actor, **data.model_dump()))


@router.get("/{owner}/{name}", summary="One model")
async def get_model(owner: str, name: str, actor: ActorDep, service: ModelServiceDep) -> ModelOut:
    return ModelOut.from_view(await service.get(actor, owner, name))


@router.patch("/{owner}/{name}", summary="Change a model: its creator, its maintainers and the admins")
async def change_model(owner: str, name: str, data: ModelChange, actor: ActorDep, service: ModelServiceDep) -> ModelOut:
    return ModelOut.from_view(await service.update(actor, owner, name, data.model_dump(exclude_unset=True)))


@router.delete(
    "/{owner}/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a model, its versions in MLflow and its files",
)
async def delete_model(owner: str, name: str, actor: ActorDep, service: ModelServiceDep) -> Response:
    await service.delete(actor, owner, name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{owner}/{name}/like", summary="Like a model (doing it again changes nothing)")
async def like_model(owner: str, name: str, actor: ActorDep, service: ModelServiceDep) -> LikeOut:
    liked, likes = await service.like(actor, owner, name)
    return LikeOut(liked=liked, likes=likes)


@router.delete("/{owner}/{name}/like", summary="Stop liking a model")
async def unlike_model(owner: str, name: str, actor: ActorDep, service: ModelServiceDep) -> LikeOut:
    liked, likes = await service.unlike(actor, owner, name)
    return LikeOut(liked=liked, likes=likes)


# ---- who has access besides its creator: only the people who may edit the model see and change it


@router.get("/{owner}/{name}/members", summary="Who has access to a model besides its creator")
async def list_members(owner: str, name: str, actor: ActorDep, service: ModelMemberServiceDep) -> list[MemberOut]:
    return [MemberOut.model_validate(member) for member in await service.list(actor, owner, name)]


@router.put("/{owner}/{name}/members/{user_id}", summary="Give somebody access, or change their role")
async def set_member(
    owner: str, name: str, user_id: str, data: MemberIn, actor: ActorDep, service: ModelMemberServiceDep
) -> MemberOut:
    return MemberOut.model_validate(await service.set(actor, owner, name, user_id, data.role))


@router.delete(
    "/{owner}/{name}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Take somebody's access away"
)
async def remove_member(
    owner: str, name: str, user_id: str, actor: ActorDep, service: ModelMemberServiceDep
) -> Response:
    await service.remove(actor, owner, name, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
