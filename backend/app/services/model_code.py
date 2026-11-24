import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models import ModelVersion
from app.models.model_version import CODE_FAILED, PINNED, RESOLVING, UNVERIFIED
from app.repositories.model_versions import ModelVersionRepository
from app.services.code_reference import parse_repository
from app.services.errors import InvalidCodeReference, InvalidSha, ModelVersionNotFound, NotBeingProcessed

logger = logging.getLogger(__name__)
# A version that has waited less than this is left alone: the job that was queued for it is probably about to start.
GRACE = timedelta(minutes=2)
_SHA = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})$")


@dataclass(frozen=True)
class CodeToResolve:
    """What the worker has to look for: a repository and what the author wrote as a reference (None: the default
    branch)."""

    url: str
    ref: str | None
    ref_kind: str


class ModelCodeResolution:
    """What the worker asks of the API while it pins the code of a version to a commit. The worker asks the host
    (GitHub, GitLab); the API keeps the records and decides: it takes the code in hand for one worker only, writes the
    commit that was found, and never changes it afterwards (a version is a snapshot: another commit is another
    version).

    - `claim`: one worker at a time; only code that is not resolved is given.
    - `pin`: the reference is a commit, now written beside what the author wrote.
    - `unverified`: the repository or the reference was not found, or is private. It is not a failure of the version.
    - `fail`: the host answered something that cannot be used.
    - `release`: the host was down or limited the calls: it waits again."""

    def __init__(
        self,
        versions: ModelVersionRepository,
        *,
        hosts: list[str],
        max_attempts: int = 3,
        stale: timedelta = timedelta(minutes=30),
    ) -> None:
        self._versions = versions
        self._hosts = hosts
        self._max_attempts = max_attempts
        self._stale = stale

    async def claim(self, version_id: uuid.UUID) -> CodeToResolve | None:
        """None when the code is not up for the taking (pinned or not verified already, taken by another worker,
        unknown, or given up after too many attempts)."""
        version = await self._versions.claim_code(version_id, datetime.now(UTC) - self._stale)
        if version is None:
            return None
        if version.code_attempts > self._max_attempts:
            await self._finish(version, CODE_FAILED, None, "The pinning was interrupted too many times")
            return None
        try:
            parse_repository(version.code_url or "", self._hosts)  # the list may have changed since it was written
        except InvalidCodeReference:
            await self._finish(version, CODE_FAILED, None, "The host of this repository is not allowed any more")
            return None
        return CodeToResolve(version.code_url or "", version.code_ref, version.code_ref_kind)

    async def pin(self, version_id: uuid.UUID, sha: str) -> ModelVersion:
        """Writes the commit. Raises InvalidSha, NotBeingProcessed (nobody holds it: it is not changed)."""
        if not _SHA.match(sha):
            raise InvalidSha
        return await self._finish(await self._held(version_id), PINNED, sha, None)

    async def unverified(self, version_id: uuid.UUID, reason: str) -> ModelVersion:
        return await self._finish(await self._held(version_id), UNVERIFIED, None, reason[:2000])

    async def fail(self, version_id: uuid.UUID, error: str) -> ModelVersion:
        return await self._finish(await self._held(version_id), CODE_FAILED, None, error[:2000])

    async def release(self, version_id: uuid.UUID) -> None:
        await self._versions.release_code(version_id)

    async def waiting(self, limit: int = 100) -> list[uuid.UUID]:
        """The code nobody is resolving: the worker queues it again. Its safety net, when Redis lost a job or a worker
        died."""
        now = datetime.now(UTC)
        return await self._versions.waiting_code(older_than=now - GRACE, stale_before=now - self._stale, limit=limit)

    async def _held(self, version_id: uuid.UUID) -> ModelVersion:
        version = await self._versions.get_by_id(version_id)
        if version is None:
            raise ModelVersionNotFound
        if version.code_state != RESOLVING:
            raise NotBeingProcessed
        return version

    async def _finish(self, version: ModelVersion, state: str, sha: str | None, error: str | None) -> ModelVersion:
        version.code_state, version.code_sha, version.code_error = state, sha, error
        await self._versions.commit()
        return version
