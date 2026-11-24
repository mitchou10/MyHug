from app.models import Dataset
from app.models.dataset import PUBLIC
from app.models.dataset_member import MAINTAINER
from app.repositories.datasets import DatasetRepository
from app.services.actor import Actor
from app.services.errors import DatasetNotFound, NotAllowed

OWNER = "owner"
ADMIN = "admin"
# Who may change a dataset or delete it.
EDITORS = (OWNER, ADMIN, MAINTAINER)


class DatasetAccess:
    """Who may do what with a dataset.

    Everybody who is logged in may read a public dataset. A private one is read by its creator, by the people who were
    given access, and by the admins. It is changed by its creator, its maintainers and the admins."""

    def __init__(self, datasets: DatasetRepository) -> None:
        self._datasets = datasets

    async def role(self, actor: Actor, dataset: Dataset) -> str | None:
        """What the actor is for this dataset: `admin`, `owner`, a member's role, or None (no access)."""
        if actor.is_admin:
            return ADMIN
        if dataset.created_by == actor.user_id:
            return OWNER
        return await self._datasets.member_role(dataset.id, actor.user_id)

    async def get_readable(self, actor: Actor, owner: str, name: str) -> tuple[Dataset, str | None]:
        """The dataset and the role of the actor, or DatasetNotFound (a private one looks like it does not exist)."""
        dataset = await self._datasets.get_by_name(owner.lower(), name.lower())
        if dataset is None:
            raise DatasetNotFound
        role = await self.role(actor, dataset)
        if dataset.visibility != PUBLIC and role is None:
            raise DatasetNotFound
        return dataset, role

    async def get_editable(self, actor: Actor, owner: str, name: str) -> Dataset:
        """The dataset, or DatasetNotFound if the actor cannot see it, or NotAllowed if they can only read it."""
        dataset, role = await self.get_readable(actor, owner, name)
        if role not in EDITORS:
            raise NotAllowed
        return dataset
