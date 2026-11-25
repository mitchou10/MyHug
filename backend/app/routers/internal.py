"""For the worker, which is a service of its own and calls the API with its key. Not for users: nothing here is in the
front end's reach, and none of it reads a file's content (the worker downloads from the storage, with signed
addresses)."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth.worker import Worker
from app.config import settings
from app.routers.deps import (
    DatasetDerivativesDep,
    DatasetProcessingDep,
    EvaluationExpiryDep,
    EvaluationProcessingDep,
    ModelCodeDep,
    ModelProcessingDep,
    ModelUploadExpiryDep,
    StorageGarbageDep,
    UploadExpiryDep,
)
from app.schemas.evaluation import Value
from app.services import tables
from app.services.dataset_processing import FileRead
from app.services.model_processing import FileChecked

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


# ---- the files of the versions of the models: the worker computes their fingerprints


class ModelFileToCheckOut(BaseModel):
    id: uuid.UUID
    path: str
    size_bytes: int
    url: str


class ModelClaimOut(BaseModel):
    claimed: bool
    files: list[ModelFileToCheckOut]


@router.post("/model-versions/{version_id}/claim", summary="Take a version of a model in hand: what to fingerprint")
async def claim_model_version(version_id: uuid.UUID, _: Worker, service: ModelProcessingDep) -> ModelClaimOut:
    files = await service.claim(version_id)
    if files is None:
        return ModelClaimOut(claimed=False, files=[])
    return ModelClaimOut(claimed=True, files=[ModelFileToCheckOut(**vars(file)) for file in files])


@router.post("/model-versions/{version_id}/result", summary="The fingerprints found in the files of a version")
async def model_version_result(
    version_id: uuid.UUID, data: ResultIn, _: Worker, service: ModelProcessingDep
) -> StatusOut:
    read = [FileChecked(id=item.id, size_bytes=item.size_bytes, sha256=item.sha256) for item in data.files]
    return StatusOut(status=(await service.complete(version_id, read)).status)


@router.post("/model-versions/{version_id}/failure", summary="A file of the version cannot be read: it is failed")
async def model_version_failure(
    version_id: uuid.UUID, data: FailureIn, _: Worker, service: ModelProcessingDep
) -> StatusOut:
    return StatusOut(status=(await service.fail(version_id, data.error)).status)


@router.post("/model-versions/{version_id}/release", summary="Put a version back to waiting (not the file's fault)")
async def model_version_release(version_id: uuid.UUID, _: Worker, service: ModelProcessingDep) -> StatusOut:
    await service.release(version_id)
    return StatusOut(status="pending")


@router.get("/model-versions/waiting", summary="The versions of models nobody is checking, for the worker to queue")
async def waiting_model_versions(_: Worker, service: ModelProcessingDep) -> WaitingOut:
    return WaitingOut(ids=await service.waiting())


# ---- the code of the versions of the models: the worker pins it to a commit


class CodeToResolveOut(BaseModel):
    claimed: bool
    url: str | None = None
    ref: str | None = None
    ref_kind: str | None = None


class CommitIn(BaseModel):
    sha: str = Field(pattern=r"^([0-9a-f]{40}|[0-9a-f]{64})$")


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class CodeStateOut(BaseModel):
    state: str


@router.post("/model-versions/{version_id}/code/claim", summary="Take the code of a version in hand: what to resolve")
async def claim_code(version_id: uuid.UUID, _: Worker, service: ModelCodeDep) -> CodeToResolveOut:
    code = await service.claim(version_id)
    if code is None:
        return CodeToResolveOut(claimed=False)
    return CodeToResolveOut(claimed=True, url=code.url, ref=code.ref, ref_kind=code.ref_kind)


@router.post("/model-versions/{version_id}/code/pinned", summary="The commit the reference points to")
async def code_pinned(version_id: uuid.UUID, data: CommitIn, _: Worker, service: ModelCodeDep) -> CodeStateOut:
    return CodeStateOut(state=(await service.pin(version_id, data.sha)).code_state)


@router.post("/model-versions/{version_id}/code/unverified", summary="Not found, or private: kept as written")
async def code_unverified(version_id: uuid.UUID, data: ReasonIn, _: Worker, service: ModelCodeDep) -> CodeStateOut:
    return CodeStateOut(state=(await service.unverified(version_id, data.reason)).code_state)


@router.post("/model-versions/{version_id}/code/failure", summary="The host answered something that cannot be used")
async def code_failure(version_id: uuid.UUID, data: ReasonIn, _: Worker, service: ModelCodeDep) -> CodeStateOut:
    return CodeStateOut(state=(await service.fail(version_id, data.reason)).code_state)


@router.post("/model-versions/{version_id}/code/release", summary="Put the code back to waiting (not its fault)")
async def code_release(version_id: uuid.UUID, _: Worker, service: ModelCodeDep) -> CodeStateOut:
    await service.release(version_id)
    return CodeStateOut(state="unresolved")


@router.get("/model-code/waiting", summary="The code nobody is resolving, for the worker to queue again")
async def waiting_code(_: Worker, service: ModelCodeDep) -> WaitingOut:
    return WaitingOut(ids=await service.waiting())


# ---- the evaluations: the worker computes their metrics from the predictions and the ground truth


class EvaluationFileOut(BaseModel):
    path: str
    url: str
    size_bytes: int


class EvaluationClaimOut(BaseModel):
    claimed: bool
    id: uuid.UUID | None = None
    task: str | None = None
    split: str | None = None
    target_column: str | None = None
    key_column: str | None = None
    prediction_column: str | None = None
    predictions: EvaluationFileOut | None = None
    predictions_format: str | None = None
    truth: list[EvaluationFileOut] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


class EvaluationResultIn(BaseModel):
    results: dict[str, Value] = Field(max_length=50)
    items: int = Field(ge=0)


class EvaluationStatusOut(BaseModel):
    status: str


@router.post("/model-evaluations/{evaluation_id}/claim", summary="Take an evaluation in hand: what to read and compute")
async def claim_evaluation(evaluation_id: uuid.UUID, _: Worker, service: EvaluationProcessingDep) -> EvaluationClaimOut:
    found = await service.claim(evaluation_id)
    if found is None:
        return EvaluationClaimOut(claimed=False)
    return EvaluationClaimOut(
        claimed=True,
        id=found.id,
        task=found.task,
        split=found.split,
        target_column=found.target_column,
        key_column=found.key_column,
        prediction_column=found.prediction_column,
        predictions=EvaluationFileOut(**vars(found.predictions)),
        predictions_format=found.predictions_format,
        truth=[EvaluationFileOut(**vars(f)) for f in found.truth],
        metrics=found.metrics,
    )


@router.post("/model-evaluations/{evaluation_id}/result", summary="The metrics that were computed")
async def evaluation_result(
    evaluation_id: uuid.UUID, data: EvaluationResultIn, _: Worker, service: EvaluationProcessingDep
) -> EvaluationStatusOut:
    return EvaluationStatusOut(status=(await service.complete(evaluation_id, data.results, data.items)).status)


@router.post(
    "/model-evaluations/{evaluation_id}/failure", summary="The predictions do not match the split: it is failed"
)
async def evaluation_failure(
    evaluation_id: uuid.UUID, data: FailureIn, _: Worker, service: EvaluationProcessingDep
) -> EvaluationStatusOut:
    return EvaluationStatusOut(status=(await service.fail(evaluation_id, data.error)).status)


@router.post("/model-evaluations/{evaluation_id}/release", summary="Put an evaluation back to waiting (not its fault)")
async def evaluation_release(
    evaluation_id: uuid.UUID, _: Worker, service: EvaluationProcessingDep
) -> EvaluationStatusOut:
    await service.release(evaluation_id)
    return EvaluationStatusOut(status="pending")


@router.get("/model-evaluations/waiting", summary="The evaluations nobody is computing, for the worker to queue")
async def waiting_evaluations(_: Worker, service: EvaluationProcessingDep) -> WaitingOut:
    return WaitingOut(ids=await service.waiting())


class ExpiredOut(BaseModel):
    expired: int


@router.post("/dataset-uploads/expire", summary="Give up the uploads that took too long and free their parts")
async def expire_uploads(
    _: Worker, datasets: UploadExpiryDep, models: ModelUploadExpiryDep, evaluations: EvaluationExpiryDep
) -> ExpiredOut:
    return ExpiredOut(
        expired=await datasets.expire_stale() + await models.expire_stale() + await evaluations.expire_stale()
    )


# ---- the copies of the files in Parquet


class ClaimedCopyOut(BaseModel):
    claimed: bool
    id: uuid.UUID | None = None
    source_url: str | None = None
    source_path: str | None = None
    source_size_bytes: int | None = None
    part_bytes: int | None = None


class PartsRequest(BaseModel):
    numbers: list[int] = Field(min_length=1, max_length=100, description="Part numbers, from 1")


class SignedPartOut(BaseModel):
    number: int
    url: str


class SignedPartsOut(BaseModel):
    parts: list[SignedPartOut]


class CopyResultIn(BaseModel):
    rows: int = Field(ge=0)
    columns: list[ColumnIn] = Field(max_length=10_000)


@router.post("/derivatives/{derivative_id}/claim", summary="Take a copy to make in hand, and get its source")
async def claim_copy(derivative_id: uuid.UUID, _: Worker, service: DatasetDerivativesDep) -> ClaimedCopyOut:
    claimed = await service.claim(derivative_id)
    if claimed is None:
        return ClaimedCopyOut(claimed=False)
    return ClaimedCopyOut(claimed=True, **vars(claimed))


@router.post("/derivatives/{derivative_id}/parts", summary="Signed addresses to send the parts of the copy to")
async def sign_copy_parts(
    derivative_id: uuid.UUID, data: PartsRequest, _: Worker, service: DatasetDerivativesDep
) -> SignedPartsOut:
    urls = await service.part_urls(derivative_id, sorted(set(data.numbers)))
    return SignedPartsOut(parts=[SignedPartOut(number=number, url=url) for number, url in urls.items()])


@router.post("/derivatives/{derivative_id}/result", summary="The copy is written: put it together and check it")
async def copy_result(
    derivative_id: uuid.UUID, data: CopyResultIn, _: Worker, service: DatasetDerivativesDep
) -> StatusOut:
    columns = [tables.Column(c.name, c.dtype) for c in data.columns]
    return StatusOut(status=(await service.complete(derivative_id, data.rows, columns)).status)


@router.post("/derivatives/{derivative_id}/failure", summary="The copy cannot be made: it is failed")
async def copy_failure(
    derivative_id: uuid.UUID, data: FailureIn, _: Worker, service: DatasetDerivativesDep
) -> StatusOut:
    return StatusOut(status=(await service.fail(derivative_id, data.error)).status)


@router.post("/derivatives/{derivative_id}/release", summary="Put a copy back to waiting (not the file's fault)")
async def release_copy(derivative_id: uuid.UUID, _: Worker, service: DatasetDerivativesDep) -> StatusOut:
    await service.release(derivative_id)
    return StatusOut(status="pending")


@router.get("/derivatives/waiting", summary="The copies nobody is making, for the worker to queue again")
async def waiting_copies(_: Worker, service: DatasetDerivativesDep) -> WaitingOut:
    return WaitingOut(ids=await service.waiting())


# ---- the objects of the storage that nothing points to


class CollectIn(BaseModel):
    after: str | None = Field(None, max_length=1024, description="Where the last pass stopped (its `next_after`)")
    dry_run: bool = Field(True, description="Only say what would be deleted. Cannot turn off the setting's dry run.")


class CollectOut(BaseModel):
    enabled: bool
    busy: bool = False
    dry_run: bool = True
    scanned: int = 0
    garbage_objects: int = 0
    garbage_bytes: int = 0
    deleted_objects: int = 0
    orphan_copies: int = 0
    started_uploads_given_up: int = 0
    missing_objects: int = 0
    missing_keys: list[str] = []
    next_after: str | None = None


@router.post("/storage/collect", summary="One pass of the collection of the objects that nothing points to")
async def collect_storage(data: CollectIn, _: Worker, service: StorageGarbageDep) -> CollectOut:
    """A pass looks at a bounded number of objects and says where to go on from (`next_after`) until it is null. The
    request can only be more careful than the configuration: it can ask for a dry run, never turn it off."""
    if not settings.STORAGE_GC_ENABLED:
        return CollectOut(enabled=False)
    result = await service.collect(after=data.after, dry_run=settings.STORAGE_GC_DRY_RUN or data.dry_run)
    return CollectOut(enabled=True, **vars(result))
