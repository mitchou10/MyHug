import uuid

from fastapi import APIRouter, Response, status

from app.auth.deps import CurrentUser
from app.routers.deps import AccessTokenServiceDep
from app.schemas import AccessTokenIn, AccessTokenOut, CreatedAccessTokenOut
from app.services.access_tokens import Owner

# Only for a person who is logged in: a token cannot make, list or revoke tokens (see `app/auth/tokens.py`).
router = APIRouter(prefix="/api/tokens", tags=["access tokens"])


@router.get("", summary="My access tokens, the newest first (never the tokens themselves)")
async def list_tokens(user: CurrentUser, service: AccessTokenServiceDep) -> list[AccessTokenOut]:
    return [AccessTokenOut.model_validate(token) for token in await service.list(user.user_id)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Make an access token for a program",
    description="The token is in this answer and nowhere else: it cannot be read again. It acts as you, with your "
    "rights on the data (read, or read and write), but never as an administrator.",
)
async def create_token(data: AccessTokenIn, user: CurrentUser, service: AccessTokenServiceDep) -> CreatedAccessTokenOut:
    owner = Owner(
        user_id=user.user_id, username=user.username or user.name or user.user_id, name=user.name, email=user.email
    )
    created = await service.create(owner, name=data.name, scope=data.scope, expires_in_days=data.expires_in_days)
    return CreatedAccessTokenOut(**AccessTokenOut.model_validate(created.token).model_dump(), token=created.secret)


@router.delete(
    "/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a token (doing it again changes nothing)"
)
async def revoke_token(token_id: uuid.UUID, user: CurrentUser, service: AccessTokenServiceDep) -> Response:
    await service.revoke(user.user_id, token_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
