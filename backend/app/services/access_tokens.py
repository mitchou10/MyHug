import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.auth import tokens
from app.config import settings
from app.models import AccessToken
from app.repositories.access_tokens import AccessTokenRepository
from app.services.errors import InvalidToken, TokenNotFound, TooManyTokens


@dataclass(frozen=True)
class Owner:
    """Who a token is made for, as the provider knows them: kept with it, since a program has no session."""

    user_id: str
    username: str
    name: str
    email: str


@dataclass(frozen=True)
class CreatedToken:
    token: AccessToken
    # The only time it exists in the clear.
    secret: str


class AccessTokenService:
    def __init__(self, repo: AccessTokenRepository) -> None:
        self._repo = repo

    async def create(self, owner: Owner, *, name: str, scope: str, expires_in_days: int | None) -> CreatedToken:
        if await self._repo.count_active(owner.user_id) >= settings.TOKENS_MAX_ACTIVE:
            raise TooManyTokens
        secret = tokens.generate()
        token = AccessToken(
            user_id=owner.user_id,
            username=owner.username,
            display_name=owner.name,
            email=owner.email,
            name=name,
            scope=scope,
            prefix=secret[: tokens.SHOWN],
            token_hash=tokens.hash_of(secret),
            expires_at=datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None,
        )
        self._repo.add(token)
        await self._repo.commit()
        return CreatedToken(token=token, secret=secret)

    async def list(self, user_id: str) -> list[AccessToken]:
        return await self._repo.list(user_id)

    async def revoke(self, user_id: str, token_id: uuid.UUID) -> None:
        """Doing it again changes nothing. Somebody else's token looks like it does not exist."""
        token = await self._repo.get(user_id, token_id)
        if token is None:
            raise TokenNotFound
        if token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)
            await self._repo.commit()

    async def authenticate(self, secret: str) -> AccessToken:
        """The token behind what a program sent, or InvalidToken: unknown, revoked and expired look the same."""
        token = await self._repo.by_hash(tokens.hash_of(secret))
        if (
            token is None
            or token.revoked_at is not None
            or (token.expires_at and token.expires_at <= datetime.now(UTC))
        ):
            raise InvalidToken
        await self._repo.touch(token.id)
        return token
