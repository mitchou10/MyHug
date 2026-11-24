import logging
import uuid

from worker.backend import Backend
from worker.celery_app import celery_app
from worker.errors import FileProblem
from worker.reader import read

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


@celery_app.task(name="datasets.process_waiting")
def process_waiting() -> int:
    """Queues the reading of the versions nobody is reading. Returns how many."""
    waiting = _backend().waiting()
    for version in waiting:
        process_version.apply_async(args=[str(version)])
    return len(waiting)


@celery_app.task(name="datasets.expire_uploads")
def expire_uploads() -> int:
    """Gives up the uploads that took too long and frees what they had received. Returns how many."""
    return _backend().expire_uploads()
