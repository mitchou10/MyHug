import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, String, cast, delete, exists, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import Dataset, DatasetLike, DatasetMember
from app.repositories.base import Repository

Sort = Literal["downloads", "likes", "updated"]


@dataclass(frozen=True)
class DatasetRow:
    """A dataset as the list shows it, with whether the person who asks likes it."""

    dataset: Dataset
    liked: bool


def _like_pattern(text: str) -> str:
    """What to look for in a search, with the characters that mean something to LIKE taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def visible_to(user_id: str, is_admin: bool) -> ColumnElement[bool]:
    """The datasets a person may see: the public ones, their own, those they were given access to. Admins see all."""
    if is_admin:
        return true()
    member = exists().where(DatasetMember.dataset_id == Dataset.id, DatasetMember.user_id == user_id)
    return or_(Dataset.visibility == "public", Dataset.created_by == user_id, member)


class DatasetRepository(Repository):
    def add(self, dataset: Dataset) -> None:
        self._db.add(dataset)

    async def get(self, dataset_id: uuid.UUID) -> Dataset | None:
        return await self._db.get(Dataset, dataset_id)

    async def get_by_name(self, owner: str, name: str) -> Dataset | None:
        result = await self._db.execute(select(Dataset).where(Dataset.owner == owner, Dataset.name == name))
        return result.scalar_one_or_none()

    async def delete(self, dataset: Dataset) -> None:
        """The members and the likes go with it (the database cascades)."""
        await self._db.execute(delete(Dataset).where(Dataset.id == dataset.id))

    async def member_role(self, dataset_id: uuid.UUID, user_id: str) -> str | None:
        result = await self._db.execute(
            select(DatasetMember.role).where(DatasetMember.dataset_id == dataset_id, DatasetMember.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def add_member(self, member: DatasetMember) -> None:
        self._db.add(member)

    async def members(self, dataset_id: uuid.UUID) -> list[DatasetMember]:
        result = await self._db.execute(
            select(DatasetMember)
            .where(DatasetMember.dataset_id == dataset_id)
            .order_by(DatasetMember.created_at, DatasetMember.user_id)
        )
        return list(result.scalars())

    async def set_member(self, dataset_id: uuid.UUID, user_id: str, role: str, added_by: str) -> None:
        """Adds the person, or changes their role if they already are a member."""
        await self._db.execute(
            pg_insert(DatasetMember)
            .values(dataset_id=dataset_id, user_id=user_id, role=role, added_by=added_by)
            .on_conflict_do_update(index_elements=["dataset_id", "user_id"], set_={"role": role})
        )

    async def remove_member(self, dataset_id: uuid.UUID, user_id: str) -> bool:
        """Whether the person was a member."""
        removed = await self._db.execute(
            delete(DatasetMember)
            .where(DatasetMember.dataset_id == dataset_id, DatasetMember.user_id == user_id)
            .returning(DatasetMember.user_id)
        )
        return removed.first() is not None

    async def is_liked(self, dataset_id: uuid.UUID, user_id: str) -> bool:
        result = await self._db.execute(
            select(exists().where(DatasetLike.dataset_id == dataset_id, DatasetLike.user_id == user_id))
        )
        return result.scalar_one()

    async def like(self, dataset_id: uuid.UUID, user_id: str) -> None:
        """Does nothing if the person already likes it: the count goes up only when a like is really added."""
        added = await self._db.execute(
            pg_insert(DatasetLike)
            .values(dataset_id=dataset_id, user_id=user_id)
            .on_conflict_do_nothing()
            .returning(DatasetLike.dataset_id)
        )
        if added.first() is not None:
            await self._db.execute(
                update(Dataset).where(Dataset.id == dataset_id).values(likes_count=Dataset.likes_count + 1)
            )

    async def unlike(self, dataset_id: uuid.UUID, user_id: str) -> None:
        removed = await self._db.execute(
            delete(DatasetLike)
            .where(DatasetLike.dataset_id == dataset_id, DatasetLike.user_id == user_id)
            .returning(DatasetLike.dataset_id)
        )
        if removed.first() is not None:
            await self._db.execute(
                update(Dataset).where(Dataset.id == dataset_id).values(likes_count=Dataset.likes_count - 1)
            )

    async def likes_count(self, dataset_id: uuid.UUID) -> int:
        result = await self._db.execute(select(Dataset.likes_count).where(Dataset.id == dataset_id))
        return result.scalar_one()

    async def page(
        self,
        *,
        user_id: str,
        is_admin: bool,
        query: str | None,
        modality: str | None,
        sort: Sort,
        limit: int,
        offset: int,
    ) -> tuple[list[DatasetRow], int]:
        """One page of the datasets the person may see, and how many there are in all.

        `query` is looked for in the address, the description and the tags."""
        conditions = [visible_to(user_id, is_admin)]
        if modality is not None:
            conditions.append(Dataset.modality == modality)
        if query:
            pattern = _like_pattern(query.strip())
            address = Dataset.owner + "/" + Dataset.name
            tags = func.array_to_string(Dataset.tags, " ")
            conditions.append(
                or_(
                    *(
                        column.ilike(pattern, escape="\\")
                        for column in (address, Dataset.description, cast(tags, String))
                    )
                )
            )

        order = {
            "downloads": (Dataset.downloads.desc(), Dataset.id.desc()),
            "likes": (Dataset.likes_count.desc(), Dataset.id.desc()),
            "updated": (Dataset.updated_at.desc(), Dataset.id.desc()),
        }[sort]
        liked = exists().where(DatasetLike.dataset_id == Dataset.id, DatasetLike.user_id == user_id)
        rows = await self._db.execute(
            select(Dataset, liked).where(*conditions).order_by(*order).limit(limit).offset(offset)
        )
        total = await self._db.execute(select(func.count()).select_from(Dataset).where(*conditions))
        return [DatasetRow(dataset, was_liked) for dataset, was_liked in rows.all()], total.scalar_one()
