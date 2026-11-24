import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError

from app.models import Model
from app.registry import MlflowLinks, ModelRegistry, registered_name
from app.repositories.models import ModelRepository, ModelRow, Sort
from app.services.actor import Actor
from app.services.datasets import namespace_of
from app.services.errors import InvalidCodeUrl, ModelNameTaken
from app.services.model_access import EDITORS, ModelAccess
from app.storage import ObjectStore


@dataclass(frozen=True)
class ModelView:
    """A model with what depends on who looks at it."""

    model: Model
    liked: bool
    can_edit: bool
    # Where to see it in MLflow: only for who can edit it, and only once MLflow knows something of it.
    mlflow_url: str | None = None


def check_code_url(url: str, hosts: list[str]) -> str:
    """The link to the code, if it is an https address of an allowed host. It is only ever kept and shown: nothing
    here fetches it."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or host not in {h.lower() for h in hosts}:
        raise InvalidCodeUrl
    return url.strip()


class ModelService:
    """Create, read, list, change, delete and like models."""

    def __init__(
        self,
        models: ModelRepository,
        access: ModelAccess,
        registry: ModelRegistry,
        links: MlflowLinks,
        store: ObjectStore,
        *,
        code_hosts: list[str],
    ) -> None:
        self._models = models
        self._access = access
        self._registry = registry
        self._links = links
        self._store = store
        self._code_hosts = code_hosts

    async def _view(self, actor: Actor, model: Model, role: str | None) -> ModelView:
        can_edit = role in EDITORS
        url = None
        if can_edit and await self._models.has_registered_versions(model.id):
            url = self._links.model(registered_name(model.owner, model.name))
        return ModelView(model, await self._models.is_liked(model.id, actor.user_id), can_edit, url)

    async def create(self, actor: Actor, *, name: str, **fields: Any) -> ModelView:
        """Raises ModelNameTaken if the person already has a model with this name, InvalidCodeUrl for a bad link.

        MLflow is not called: a model only appears there with its first version."""
        if fields.get("code_url"):
            fields["code_url"] = check_code_url(fields["code_url"], self._code_hosts)
        owner = namespace_of(actor)
        if await self._models.get_by_name(owner, name) is not None:
            raise ModelNameTaken
        model = Model(
            id=uuid.uuid4(),
            owner=owner,
            name=name,
            created_by=actor.user_id,
            created_by_username=actor.username,
            **fields,
        )
        self._models.add(model)
        try:
            await self._models.commit()
        except IntegrityError:  # two requests with the same name at once: the database decides
            raise ModelNameTaken from None
        return await self.get(actor, owner, name)

    async def get(self, actor: Actor, owner: str, name: str) -> ModelView:
        model, role = await self._access.get_readable(actor, owner, name)
        return await self._view(actor, model, role)

    async def list_page(
        self,
        actor: Actor,
        *,
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
        return await self._models.page(
            user_id=actor.user_id,
            is_admin=actor.is_admin,
            query=query,
            owner=owner,
            task=task,
            modality=modality,
            library=library,
            language=language,
            license=license,
            tags=tags,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    async def update(self, actor: Actor, owner: str, name: str, changes: dict[str, Any]) -> ModelView:
        """Changes what is in `changes`. Raises ModelNotFound, or NotAllowed for somebody who may only read."""
        model = await self._access.get_editable(actor, owner, name)
        if changes.get("code_url"):
            changes["code_url"] = check_code_url(changes["code_url"], self._code_hosts)
        for column, value in changes.items():
            setattr(model, column, value)
        model.updated_at = datetime.now(UTC)
        await self._models.commit()
        return await self.get(actor, owner, name)

    async def delete(self, actor: Actor, owner: str, name: str) -> None:
        """MLflow first, the database last: if MLflow does not answer, nothing is deleted and the call can be made again
        (deleting in MLflow does nothing for what is already gone). A model that MLflow never knew does not need it."""
        model = await self._access.get_editable(actor, owner, name)
        keys = await self._models.storage_keys(model.id)
        if await self._models.has_registered_versions(model.id):
            await self._registry.delete_model(registered_name(model.owner, model.name))
        await self._models.delete(model)
        await self._models.commit()
        for key in keys:  # the files go once the model is really gone
            await self._store.delete(key)

    async def like(self, actor: Actor, owner: str, name: str) -> tuple[bool, int]:
        """Likes a model the person can see; liking it again changes nothing. Returns (liked, how many)."""
        model, _ = await self._access.get_readable(actor, owner, name)
        await self._models.like(model.id, actor.user_id)
        await self._models.commit()
        return True, await self._models.likes_count(model.id)

    async def unlike(self, actor: Actor, owner: str, name: str) -> tuple[bool, int]:
        model, _ = await self._access.get_readable(actor, owner, name)
        await self._models.unlike(model.id, actor.user_id)
        await self._models.commit()
        return False, await self._models.likes_count(model.id)
