import uuid

from fastapi import APIRouter, Query, Response, status

from app.config import settings
from app.routers.deps import ActorDep, ModelUploadServiceDep, ModelVersionServiceDep
from app.schemas import ModelUploadIn, ModelVersionOut, PartsIn, PartsOut, UploadOut
from app.schemas.dataset import SignedPartOut
from app.services.dataset_uploads import PlannedFile

router = APIRouter(tags=["model uploads"])


@router.post(
    "/api/models/{owner}/{name}/uploads",
    status_code=status.HTTP_201_CREATED,
    summary="Announce the files of a new version: they will be sent straight to the storage, in parts",
)
async def start_upload(
    owner: str, name: str, data: ModelUploadIn, actor: ActorDep, service: ModelUploadServiceDep
) -> UploadOut:
    files = [PlannedFile(path=f.path, size=f.size, content_type=f.content_type, sha256=f.sha256) for f in data.files]
    code = data.code.model_dump() if data.code else None
    return UploadOut.from_view(
        await service.start(actor, owner, name, files=files, remove=data.remove, message=data.message, code=code)
    )


@router.get(
    "/api/model-uploads/{upload_id}", summary="An upload, and with `parts` what reached the storage (to resume it)"
)
async def get_upload(
    upload_id: uuid.UUID, actor: ActorDep, service: ModelUploadServiceDep, parts: bool = Query(False)
) -> UploadOut:
    return UploadOut.from_view(await service.get(actor, upload_id, parts=parts))


@router.post("/api/model-uploads/{upload_id}/parts", summary="Signed addresses to send parts of a file to")
async def sign_parts(upload_id: uuid.UUID, data: PartsIn, actor: ActorDep, service: ModelUploadServiceDep) -> PartsOut:
    signed = await service.part_urls(actor, upload_id, data.file_id, data.numbers)
    return PartsOut(
        parts=[SignedPartOut(number=n, url=url) for n, url in signed], expires_in=settings.SIGNED_ADDRESS_SECONDS
    )


@router.post(
    "/api/model-uploads/{upload_id}/complete",
    summary="Put the parts together, make the version and register it in MLflow",
)
async def complete_upload(
    upload_id: uuid.UUID,
    actor: ActorDep,
    uploads: ModelUploadServiceDep,
    versions: ModelVersionServiceDep,
) -> ModelVersionOut:
    version = await uploads.complete(actor, upload_id)
    return ModelVersionOut.from_view(await versions.view_of(actor, version))


@router.delete("/api/model-uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Give up an upload")
async def abort_upload(upload_id: uuid.UUID, actor: ActorDep, service: ModelUploadServiceDep) -> Response:
    await service.abort(actor, upload_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
