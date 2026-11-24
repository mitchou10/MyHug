import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, String, cast, delete, exists, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import Model, ModelFile, ModelLike, ModelMember, ModelVersion
from app.repositories.base import Repository

Sort = Literal["downloads", "likes", "updated"]


@dataclass(frozen=True)
class ModelRow:
    """A model as the list shows it, with whether the person who asks likes it."""

    model: Model
    liked: bool


def _like_pattern(text: str) -> str:
    """What to look for in a search, with the characters that mean something to LIKE taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def visible_to(user_id: str, is_admin: bool) -> ColumnElement[bool]:
    """The models a person may see: the public ones, their own, those they were given access to. Admins see all."""
    if is_admin:
        return true()
    member = exists().where(ModelMember.model_id == Model.id, ModelMember.user_id == user_id)
    return or_(Model.visibility == "public", Model.created_by == user_id, member)


class ModelRepository(Repository):
    def add(self, model: Model) -> None:
        self._db.add(model)

    async def get(self, model_id: uuid.UUID) -> Model | None:
        return await self._db.get(Model, model_id)

    async def get_by_name(self, owner: str, name: str) -> Model | None:
        result = await self._db.execute(select(Model).where(Model.owner == owner, Model.name == name))
        return result.scalar_one_or_none()

    async def lock(self, model_id: uuid.UUID) -> None:
        """Waits for any other request that is changing the versions of this model, until the end of the transaction."""
        await self._db.execute(select(Model.id).where(Model.id == model_id).with_for_update())

    async def delete(self, model: Model) -> None:
        """The members, the likes, the versions and their files go with it (the database cascades)."""
        await self._db.execute(delete(Model).where(Model.id == model.id))

    async def has_registered_versions(self, model_id: uuid.UUID) -> bool:
        """Whether MLflow knows something of this model: a version that points to it."""
        result = await self._db.execute(
            select(exists().where(ModelVersion.model_id == model_id, ModelVersion.mlflow_name.is_not(None)))
        )
        return result.scalar_one()

    async def storage_keys(self, model_id: uuid.UUID) -> set[str]:
        """Where the content of every file of every version is: what is to be removed with the model."""
        result = await self._db.execute(
            select(ModelFile.storage_key).join(ModelVersion).where(ModelVersion.model_id == model_id).distinct()
        )
        return set(result.scalars())

    # ---- members

    async def member_role(self, model_id: uuid.UUID, user_id: str) -> str | None:
        result = await self._db.execute(
            select(ModelMember.role).where(ModelMember.model_id == model_id, ModelMember.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def members(self, model_id: uuid.UUID) -> list[ModelMember]:
        result = await self._db.execute(
            select(ModelMember)
            .where(ModelMember.model_id == model_id)
            .order_by(ModelMember.created_at, ModelMember.user_id)
        )
        return list(result.scalars())

    async def set_member(self, model_id: uuid.UUID, user_id: str, role: str, added_by: str) -> None:
        """Adds the person, or changes their role if they already are a member."""
        await self._db.execute(
            pg_insert(ModelMember)
            .values(model_id=model_id, user_id=user_id, role=role, added_by=added_by)
            .on_conflict_do_update(index_elements=["model_id", "user_id"], set_={"role": role})
        )

    async def remove_member(self, model_id: uuid.UUID, user_id: str) -> bool:
        """Whether the person was a member."""
        removed = await self._db.execute(
            delete(ModelMember)
            .where(ModelMember.model_id == model_id, ModelMember.user_id == user_id)
            .returning(ModelMember.user_id)
        )
        return removed.first() is not None

    # ---- likes

    async def is_liked(self, model_id: uuid.UUID, user_id: str) -> bool:
        result = await self._db.execute(
            select(exists().where(ModelLike.model_id == model_id, ModelLike.user_id == user_id))
        )
        return result.scalar_one()

    async def like(self, model_id: uuid.UUID, user_id: str) -> None:
        """Does nothing if the person already likes it: the count goes up only when a like is really added."""
        added = await self._db.execute(
            pg_insert(ModelLike)
            .values(model_id=model_id, user_id=user_id)
            .on_conflict_do_nothing()
            .returning(ModelLike.model_id)
        )
        if added.first() is not None:
            await self._db.execute(update(Model).where(Model.id == model_id).values(likes_count=Model.likes_count + 1))

    async def unlike(self, model_id: uuid.UUID, user_id: str) -> None:
        removed = await self._db.execute(
            delete(ModelLike)
            .where(ModelLike.model_id == model_id, ModelLike.user_id == user_id)
            .returning(ModelLike.model_id)
        )
        if removed.first() is not None:
            await self._db.execute(update(Model).where(Model.id == model_id).values(likes_count=Model.likes_count - 1))

    async def likes_count(self, model_id: uuid.UUID) -> int:
        result = await self._db.execute(select(Model.likes_count).where(Model.id == model_id))
        return result.scalar_one()

    # ---- the list

    async def page(
        self,
        *,
        user_id: str,
        is_admin: bool,
        query: str | None,
        owner: str | None,
        task: str | None,
        modality: str | None,
        library: str | None,
        language: str | None,
        license: str | None,
        tags: list[str],
        sort: Sort,
        limit: int,
        offset: int,
    ) -> tuple[list[ModelRow], int]:
        """One page of the models the person may see, and how many there are in all.

        `query` is looked for in the address, the description and the tags. `tags` must all be on the model."""
        conditions = [visible_to(user_id, is_admin)]
        if owner:
            conditions.append(Model.owner == owner.lower())
        if task:
            conditions.append(Model.tasks.contains([task]))
        if modality:
            conditions.append(Model.inputs.contains([modality]))
        if library:
            conditions.append(func.lower(Model.library) == library.lower())
        if language:
            conditions.append(Model.languages.contains([language]))
        if license:
            conditions.append(func.lower(Model.license) == license.lower())
        if tags:
            conditions.append(Model.tags.contains(tags))
        if query:
            pattern = _like_pattern(query.strip())
            address = Model.owner + "/" + Model.name
            tag_text = func.array_to_string(Model.tags, " ")
            conditions.append(
                or_(
                    *(
                        column.ilike(pattern, escape="\\")
                        for column in (address, Model.description, cast(tag_text, String))
                    )
                )
            )

        order = {
            "downloads": (Model.downloads.desc(), Model.id.desc()),
            "likes": (Model.likes_count.desc(), Model.id.desc()),
            "updated": (Model.updated_at.desc(), Model.id.desc()),
        }[sort]
        liked = exists().where(ModelLike.model_id == Model.id, ModelLike.user_id == user_id)
        rows = await self._db.execute(
            select(Model, liked).where(*conditions).order_by(*order).limit(limit).offset(offset)
        )
        total = await self._db.execute(select(func.count()).select_from(Model).where(*conditions))
        return [ModelRow(model, was_liked) for model, was_liked in rows.all()], total.scalar_one()
