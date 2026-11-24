import uuid

from fastapi import APIRouter, Query, Response, status

from app.config import settings
from app.routers.deps import ActorDep, DatasetUploadServiceDep
from app.schemas import PartsIn, PartsOut, UploadIn, UploadOut, VersionOut
from app.schemas.dataset import SignedPartOut
from app.services.dataset_uploads import PlannedFile

router = APIRouter(tags=["dataset uploads"])


@router.post(
    "/api/datasets/{owner}/{name}/uploads",
    status_code=status.HTTP_201_CREATED,
    summary="Announce the files of a new version: they will be sent straight to the storage, in parts",
)
async def start_upload(
    owner: str, name: str, data: UploadIn, actor: ActorDep, service: DatasetUploadServiceDep
) -> UploadOut:
    files = [PlannedFile(path=f.path, size=f.size, content_type=f.content_type, sha256=f.sha256) for f in data.files]
    return UploadOut.from_view(
        await service.start(actor, owner, name, files=files, remove=data.remove, message=data.message)
    )


@router.get("/api/uploads/{upload_id}", summary="An upload, and with `parts` what reached the storage (to resume it)")
async def get_upload(
    upload_id: uuid.UUID, actor: ActorDep, service: DatasetUploadServiceDep, parts: bool = Query(False)
) -> UploadOut:
    return UploadOut.from_view(await service.get(actor, upload_id, parts=parts))


@router.post("/api/uploads/{upload_id}/parts", summary="Signed addresses to send parts of a file to")
async def sign_parts(
    upload_id: uuid.UUID, data: PartsIn, actor: ActorDep, service: DatasetUploadServiceDep
) -> PartsOut:
    signed = await service.part_urls(actor, upload_id, data.file_id, data.numbers)
    return PartsOut(
        parts=[SignedPartOut(number=n, url=url) for n, url in signed], expires_in=settings.SIGNED_ADDRESS_SECONDS
    )


@router.post("/api/uploads/{upload_id}/complete", summary="Put the parts together and make the version")
async def complete_upload(upload_id: uuid.UUID, actor: ActorDep, service: DatasetUploadServiceDep) -> VersionOut:
    return VersionOut.model_validate(await service.complete(actor, upload_id))


@router.delete("/api/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Give up an upload")
async def abort_upload(upload_id: uuid.UUID, actor: ActorDep, service: DatasetUploadServiceDep) -> Response:
    await service.abort(actor, upload_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
