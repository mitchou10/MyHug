import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.models import Dataset
from app.repositories.dataset_uploads import DatasetUploadRepository
from app.repositories.dataset_versions import DatasetVersionRepository
from app.repositories.datasets import DatasetRepository, DatasetRow, Sort
from app.services.actor import Actor
from app.services.dataset_access import EDITORS, DatasetAccess
from app.services.dataset_versions import SplitInfo, splits_of
from app.services.errors import DatasetNameTaken
from app.storage import ObjectStore


@dataclass(frozen=True)
class DatasetView:
    """A dataset with what depends on who looks at it."""

    dataset: Dataset
    liked: bool
    can_edit: bool
    # The parts of the latest version and the columns of its rows: nothing for a dataset without files.
    splits: list[SplitInfo] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    # Where the latest version is (pending, processing, ready, failed), None without files.
    processing: str | None = None


def namespace_of(actor: Actor) -> str:
    """Where the datasets of a person live: their name, made of what an address allows (lowercase letters, digits,
    dots, dashes, underscores)."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", actor.username.lower()).strip("-._")
    return slug[:100] or "user"


class DatasetService:
    """Create, read, list, change, delete and like datasets."""

    def __init__(
        self,
        datasets: DatasetRepository,
        access: DatasetAccess,
        versions: DatasetVersionRepository,
        uploads: DatasetUploadRepository,
        store: ObjectStore,
    ) -> None:
        self._datasets = datasets
        self._access = access
        self._versions = versions
        self._uploads = uploads
        self._store = store

    async def _view(self, actor: Actor, dataset: Dataset, role: str | None) -> DatasetView:
        liked = await self._datasets.is_liked(dataset.id, actor.user_id)
        latest = await self._versions.latest(dataset.id)
        files = await self._versions.files(latest.id) if latest else []
        return DatasetView(
            dataset,
            liked,
            role in EDITORS,
            splits_of(files),
            latest.columns if latest else [],
            latest.status if latest else None,
        )

    async def create(self, actor: Actor, *, name: str, **fields: Any) -> DatasetView:
        """Raises DatasetNameTaken if the person already has a dataset with this name."""
        owner = namespace_of(actor)
        if await self._datasets.get_by_name(owner, name) is not None:
            raise DatasetNameTaken
        dataset = Dataset(
            id=uuid.uuid4(),
            owner=owner,
            name=name,
            created_by=actor.user_id,
            created_by_username=actor.username,
            **fields,
        )
        self._datasets.add(dataset)
        try:
            await self._datasets.commit()
        except IntegrityError:  # two requests with the same name at once: the database decides
            raise DatasetNameTaken from None
        dataset, role = await self._access.get_readable(actor, owner, name)
        return await self._view(actor, dataset, role)

    async def get(self, actor: Actor, owner: str, name: str) -> DatasetView:
        dataset, role = await self._access.get_readable(actor, owner, name)
        return await self._view(actor, dataset, role)

    async def list_page(
        self, actor: Actor, *, query: str | None, modality: str | None, sort: Sort, limit: int, offset: int
    ) -> tuple[list[DatasetRow], int]:
        return await self._datasets.page(
            user_id=actor.user_id,
            is_admin=actor.is_admin,
            query=query,
            modality=modality,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    async def update(self, actor: Actor, owner: str, name: str, changes: dict[str, Any]) -> DatasetView:
        """Changes what is in `changes`. Raises DatasetNotFound, or NotAllowed for somebody who may only read."""
        dataset = await self._access.get_editable(actor, owner, name)
        for column, value in changes.items():
            setattr(dataset, column, value)
        dataset.updated_at = datetime.now(UTC)
        await self._datasets.commit()
        return await self.get(actor, owner, name)

    async def delete(self, actor: Actor, owner: str, name: str) -> None:
        dataset = await self._access.get_editable(actor, owner, name)
        keys = await self._versions.storage_keys(dataset.id)
        going_on = await self._uploads.open_files(dataset.id)
        await self._datasets.delete(dataset)
        await self._datasets.commit()
        for key in keys:  # the files go once the dataset is really gone
            await self._store.delete(key)
        for file in going_on:  # and what was being uploaded is given up
            await self._store.abort_multipart(file.storage_key, file.multipart_id)

    async def like(self, actor: Actor, owner: str, name: str) -> tuple[bool, int]:
        """Likes a dataset the person can see; liking it again changes nothing. Returns (liked, how many)."""
        dataset, _ = await self._access.get_readable(actor, owner, name)
        await self._datasets.like(dataset.id, actor.user_id)
        await self._datasets.commit()
        return True, await self._datasets.likes_count(dataset.id)

    async def unlike(self, actor: Actor, owner: str, name: str) -> tuple[bool, int]:
        dataset, _ = await self._access.get_readable(actor, owner, name)
        await self._datasets.unlike(dataset.id, actor.user_id)
        await self._datasets.commit()
        return False, await self._datasets.likes_count(dataset.id)
