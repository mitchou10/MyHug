from fastapi import APIRouter, Response, status

from app.routers.deps import ActorDep, DatasetMemberServiceDep
from app.schemas import DatasetMemberIn, DatasetMemberOut

# Who has access besides the creator: only the people who may edit the dataset see and change it.
router = APIRouter(prefix="/api/datasets/{owner}/{name}/members", tags=["datasets"])


@router.get("", summary="Who has access to a dataset besides its creator")
async def list_members(
    owner: str, name: str, actor: ActorDep, service: DatasetMemberServiceDep
) -> list[DatasetMemberOut]:
    return [DatasetMemberOut.model_validate(member) for member in await service.list(actor, owner, name)]


@router.put("/{user_id}", summary="Give somebody access, or change their role")
async def set_member(
    owner: str, name: str, user_id: str, data: DatasetMemberIn, actor: ActorDep, service: DatasetMemberServiceDep
) -> DatasetMemberOut:
    return DatasetMemberOut.model_validate(await service.set(actor, owner, name, user_id, data.role))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Take somebody's access away")
async def remove_member(
    owner: str, name: str, user_id: str, actor: ActorDep, service: DatasetMemberServiceDep
) -> Response:
    await service.remove(actor, owner, name, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
