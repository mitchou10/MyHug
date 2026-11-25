from app.models import DatasetMember
from app.repositories.datasets import DatasetRepository
from app.services.actor import Actor
from app.services.dataset_access import DatasetAccess
from app.services.errors import InvalidMember, MemberNotFound


class DatasetMemberService:
    """Who has access to a dataset besides its creator. Only the people who may edit the dataset manage it."""

    def __init__(self, datasets: DatasetRepository, access: DatasetAccess) -> None:
        self._datasets = datasets
        self._access = access

    async def list(self, actor: Actor, owner: str, name: str) -> list[DatasetMember]:
        dataset = await self._access.get_editable(actor, owner, name)
        return await self._datasets.members(dataset.id)

    async def set(self, actor: Actor, owner: str, name: str, user_id: str, role: str) -> DatasetMember:
        """Adds the person, or changes their role. Raises InvalidMember for the creator of the dataset."""
        dataset = await self._access.get_editable(actor, owner, name)
        if user_id == dataset.created_by:
            raise InvalidMember
        await self._datasets.set_member(dataset.id, user_id, role, actor.user_id)
        await self._datasets.commit()
        return next(member for member in await self._datasets.members(dataset.id) if member.user_id == user_id)

    async def remove(self, actor: Actor, owner: str, name: str, user_id: str) -> None:
        dataset = await self._access.get_editable(actor, owner, name)
        if not await self._datasets.remove_member(dataset.id, user_id):
            raise MemberNotFound
        await self._datasets.commit()
