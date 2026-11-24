from app.models import Model
from app.models.dataset import PUBLIC
from app.models.model_member import MAINTAINER
from app.repositories.models import ModelRepository
from app.services.actor import Actor
from app.services.errors import ModelNotFound, NotAllowed

OWNER = "owner"
ADMIN = "admin"
# Who may change a model, delete it, and manage who has access to it.
EDITORS = (OWNER, ADMIN, MAINTAINER)


class ModelAccess:
    """Who may do what with a model, the same rules as for a dataset.

    Everybody who is logged in may read a public model. A private one is read by its creator, by the people who were
    given access, and by the admins. It is changed by its creator, its maintainers and the admins."""

    def __init__(self, models: ModelRepository) -> None:
        self._models = models

    async def role(self, actor: Actor, model: Model) -> str | None:
        """What the actor is for this model: `admin`, `owner`, a member's role, or None (no access)."""
        if actor.is_admin:
            return ADMIN
        if model.created_by == actor.user_id:
            return OWNER
        return await self._models.member_role(model.id, actor.user_id)

    async def get_readable(self, actor: Actor, owner: str, name: str) -> tuple[Model, str | None]:
        """The model and the role of the actor, or ModelNotFound (a private one looks like it does not exist)."""
        model = await self._models.get_by_name(owner.lower(), name.lower())
        if model is None:
            raise ModelNotFound
        role = await self.role(actor, model)
        if model.visibility != PUBLIC and role is None:
            raise ModelNotFound
        return model, role

    async def get_editable(self, actor: Actor, owner: str, name: str) -> Model:
        """The model, or ModelNotFound if the actor cannot see it, or NotAllowed if they can only read it."""
        model, role = await self.get_readable(actor, owner, name)
        if role not in EDITORS:
            raise NotAllowed
        return model
