from app.models import ModelMember
from app.repositories.models import ModelRepository
from app.services.actor import Actor
from app.services.errors import InvalidMember, MemberNotFound
from app.services.model_access import ModelAccess


class ModelMemberService:
    """Who has access to a model besides its creator. Only the people who may edit the model manage it."""

    def __init__(self, models: ModelRepository, access: ModelAccess) -> None:
        self._models = models
        self._access = access

    async def list(self, actor: Actor, owner: str, name: str) -> list[ModelMember]:
        model = await self._access.get_editable(actor, owner, name)
        return await self._models.members(model.id)

    async def set(self, actor: Actor, owner: str, name: str, user_id: str, role: str) -> ModelMember:
        """Adds the person, or changes their role. Raises InvalidMember for the creator of the model."""
        model = await self._access.get_editable(actor, owner, name)
        if user_id == model.created_by:
            raise InvalidMember
        await self._models.set_member(model.id, user_id, role, actor.user_id)
        await self._models.commit()
        return next(member for member in await self._models.members(model.id) if member.user_id == user_id)

    async def remove(self, actor: Actor, owner: str, name: str, user_id: str) -> None:
        model = await self._access.get_editable(actor, owner, name)
        if not await self._models.remove_member(model.id, user_id):
            raise MemberNotFound
        await self._models.commit()
