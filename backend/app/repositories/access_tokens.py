import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update

from app.models import AccessToken
from app.repositories.base import Repository

# A token is marked as used at most this often: a busy script must not write at every call.
TOUCH_EVERY = timedelta(minutes=1)


class AccessTokenRepository(Repository):
    def add(self, token: AccessToken) -> None:
        self._db.add(token)

    async def get(self, user_id: str, token_id: uuid.UUID) -> AccessToken | None:
        """Looked up with its owner: somebody else's token finds nothing."""
        result = await self._db.execute(
            select(AccessToken).where(AccessToken.id == token_id, AccessToken.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def by_hash(self, token_hash: str) -> AccessToken | None:
        result = await self._db.execute(select(AccessToken).where(AccessToken.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def list(self, user_id: str) -> list[AccessToken]:
        result = await self._db.execute(
            select(AccessToken)
            .where(AccessToken.user_id == user_id)
            .order_by(AccessToken.created_at.desc(), AccessToken.id)
        )
        return list(result.scalars().all())

    async def count_active(self, user_id: str) -> int:
        now = datetime.now(UTC)
        result = await self._db.execute(
            select(func.count())
            .select_from(AccessToken)
            .where(
                AccessToken.user_id == user_id,
                AccessToken.revoked_at.is_(None),
                or_(AccessToken.expires_at.is_(None), AccessToken.expires_at > now),
            )
        )
        return result.scalar_one()

    async def touch(self, token_id: uuid.UUID) -> None:
        """Says the token was used now, unless it was said less than a minute ago."""
        now = datetime.now(UTC)
        await self._db.execute(
            update(AccessToken)
            .where(
                AccessToken.id == token_id,
                or_(AccessToken.last_used_at.is_(None), AccessToken.last_used_at < now - TOUCH_EVERY),
            )
            .values(last_used_at=now)
        )
        await self._db.commit()
