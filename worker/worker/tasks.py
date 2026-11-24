import logging
import uuid

from worker.backend import Backend
from worker.celery_app import celery_app
from worker.config import settings
from worker.copier import make_copy
from worker.errors import FileProblem
from worker.reader import fingerprint, read

logger = logging.getLogger(__name__)


def _backend() -> Backend:
    return Backend()


@celery_app.task(
    name="datasets.process_version",  # the name the API queues it by
    autoretry_for=(Exception,),  # what is not the file's fault: the API or the storage was down
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def process_version(version_id: str) -> str | None:
    """Reads the files of a version and tells the API what they hold. Returns where the version ended, or None when
    there was nothing to do (read already, or taken by another worker)."""
    api, version = _backend(), uuid.UUID(version_id)
    files = api.claim(version)
    if files is None:
        return None
    try:
        found = [read(api, file) for file in files]
    except FileProblem as error:
        logger.warning("Version %s cannot be read: %s", version, error)
        return api.failure(version, str(error))
    except Exception:
        api.release(version)  # not the file's fault: it is taken again by the retry
        raise
    return api.result(version, found)


@celery_app.task(
    name="models.process_version",  # the name the API queues it by
    autoretry_for=(Exception,),  # what is not the file's fault: the API or the storage was down
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def process_model_version(version_id: str) -> str | None:
    """Computes the fingerprints of the files of a version of a model, and tells the API, which compares them with what
    was announced. Returns where the version ended, or None when there was nothing to do."""
    api, version = _backend(), uuid.UUID(version_id)
    files = api.claim_model_version(version)
    if files is None:
        return None
    try:
        found = [fingerprint(api, file) for file in files]
    except FileProblem as error:
        logger.warning("Model version %s cannot be read: %s", version, error)
        return api.model_version_failure(version, str(error))
    except Exception:
        api.model_version_release(version)  # not the file's fault: it is taken again by the retry
        raise
    return api.model_version_result(version, found)


@celery_app.task(
    name="datasets.convert_file",  # the name the API queues it by
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def convert_file(derivative_id: str) -> str | None:
    """Makes the Parquet copy of a tabular file and tells the API. Returns where the copy ended, or None when there was
    nothing to do. A copy that cannot be made never fails the dataset: the API goes on reading the original."""
    api, derivative = _backend(), uuid.UUID(derivative_id)
    copy = api.claim_copy(derivative)
    if copy is None:
        return None
    try:
        rows, columns = make_copy(api, copy)
    except FileProblem as error:
        logger.warning("The copy %s cannot be made: %s", derivative, error)
        return api.copy_failure(derivative, str(error))
    except Exception:
        api.copy_release(derivative)  # not the file's fault: it is taken again by the retry
        raise
    return api.copy_result(derivative, rows, [{"name": column.name, "dtype": column.dtype} for column in columns])


@celery_app.task(name="datasets.process_waiting")
def process_waiting() -> int:
    """Queues the jobs nobody is doing: the reading of versions (of datasets and of models) and the making of copies.
    Returns how many."""
    api = _backend()
    versions, copies = api.waiting(), api.waiting_copies()
    models = api.waiting_model_versions()
    for version in versions:
        process_version.apply_async(args=[str(version)])
    for model_version in models:
        process_model_version.apply_async(args=[str(model_version)])
    for copy in copies:
        convert_file.apply_async(args=[str(copy)])
    return len(versions) + len(copies) + len(models)


@celery_app.task(name="datasets.expire_uploads")
def expire_uploads() -> int:
    """Gives up the uploads that took too long and frees what they had received. Returns how many."""
    return _backend().expire_uploads()


@celery_app.task(name="storage.collect")
def collect_storage() -> dict[str, int | bool]:
    """Asks the backend to collect the objects of the storage that nothing points to, pass after pass (each is bounded)
    until it has seen everything. The backend decides what is garbage and whether to delete it: this only asks."""
    api = _backend()
    totals: dict[str, int | bool] = {"passes": 0, "scanned": 0, "garbage_objects": 0, "deleted_objects": 0}
    after: str | None = None
    for _ in range(settings.COLLECT_MAX_PASSES):
        done = api.collect_storage(after)
        if not done["enabled"]:
            return {**totals, "enabled": False}
        if done["busy"]:  # another pass is running: this one is not needed
            return {**totals, "busy": True}
        totals["passes"] += 1
        for name in ("scanned", "garbage_objects", "deleted_objects"):
            totals[name] += done[name]
        after = done["next_after"]
        if after is None:
            break
    return totals
