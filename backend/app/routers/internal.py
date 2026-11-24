"""For the worker, which is a service of its own and calls the API with its key. Not for users: nothing here is in the
front end's reach, and none of it reads a file's content (the worker downloads from the storage, with signed
addresses)."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth.worker import Worker
from app.routers.deps import DatasetProcessingDep, UploadExpiryDep
from app.services import tables
from app.services.dataset_processing import FileRead

router = APIRouter(prefix="/api/internal", tags=["worker"])


class ColumnIn(BaseModel):
    name: str = Field(max_length=1000)
    dtype: str = Field(max_length=50)


class FileReadIn(BaseModel):
    id: uuid.UUID
    size_bytes: int = Field(ge=0)
    sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    rows: int | None = Field(None, ge=0)
    columns: list[ColumnIn] | None = Field(None, max_length=10_000)


class ResultIn(BaseModel):
    files: list[FileReadIn] = Field(max_length=1000)


class FailureIn(BaseModel):
    error: str = Field(max_length=2000)


class FileToReadOut(BaseModel):
    id: uuid.UUID
    path: str
    size_bytes: int
    url: str
    needs_fingerprint: bool
    needs_rows: bool


class ClaimOut(BaseModel):
    # False: nothing to do (read already, taken by another worker, unknown, or given up).
    claimed: bool
    files: list[FileToReadOut]


class StatusOut(BaseModel):
    status: str


@router.post("/dataset-versions/{version_id}/claim", summary="Take a version in hand, and get what is to be read in it")
async def claim(version_id: uuid.UUID, _: Worker, service: DatasetProcessingDep) -> ClaimOut:
    files = await service.claim(version_id)
    if files is None:
        return ClaimOut(claimed=False, files=[])
    return ClaimOut(claimed=True, files=[FileToReadOut(**vars(file)) for file in files])


@router.post("/dataset-versions/{version_id}/result", summary="What was found in the files of a version")
async def result(version_id: uuid.UUID, data: ResultIn, _: Worker, service: DatasetProcessingDep) -> StatusOut:
    read = [
        FileRead(
            id=item.id,
            size_bytes=item.size_bytes,
            sha256=item.sha256,
            rows=item.rows,
            columns=[tables.Column(c.name, c.dtype) for c in item.columns] if item.columns is not None else None,
        )
        for item in data.files
    ]
    return StatusOut(status=(await service.complete(version_id, read)).status)


@router.post("/dataset-versions/{version_id}/failure", summary="A file of the version cannot be read: it is failed")
async def failure(version_id: uuid.UUID, data: FailureIn, _: Worker, service: DatasetProcessingDep) -> StatusOut:
    return StatusOut(status=(await service.fail(version_id, data.error)).status)


@router.post("/dataset-versions/{version_id}/release", summary="Put a version back to waiting (not the file's fault)")
async def release(version_id: uuid.UUID, _: Worker, service: DatasetProcessingDep) -> StatusOut:
    await service.release(version_id)
    return StatusOut(status="pending")


class WaitingOut(BaseModel):
    ids: list[uuid.UUID]


@router.get("/dataset-versions/waiting", summary="The versions nobody is reading, for the worker to queue again")
async def waiting(_: Worker, service: DatasetProcessingDep) -> WaitingOut:
    return WaitingOut(ids=await service.waiting())


class ExpiredOut(BaseModel):
    expired: int


@router.post("/dataset-uploads/expire", summary="Give up the uploads that took too long and free their parts")
async def expire_uploads(_: Worker, service: UploadExpiryDep) -> ExpiredOut:
    return ExpiredOut(expired=await service.expire_stale())
