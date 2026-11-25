from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import oidc, tokens
from app.auth.context import RequestContext, context_from_claims
from app.auth.session import MemorySessionStore, Session, SessionStore, now
from app.config import settings
from app.db import get_db
from app.repositories.access_tokens import AccessTokenRepository
from app.services.access_tokens import AccessTokenService
from app.services.errors import InvalidToken
from app.serving import RateLimiter, get_rate_limiter

store: SessionStore = MemorySessionStore()

# Refresh a little before the access token really expires.
LEEWAY_SECONDS = 30


def set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        sid,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )


async def session_of(request: Request) -> Session | None:
    """The session behind the cookie (access token refreshed if needed), or None."""
    sid = request.cookies.get(settings.SESSION_COOKIE_NAME)
    session = store.get(sid) if sid else None
    if sid is None or session is None:
        return None
    if now() - session.created_at > settings.SESSION_TTL_SECONDS:
        store.delete(sid)
        return None
    if session.expires_at - LEEWAY_SECONDS > now():
        return session
    if not session.refresh_token:
        store.delete(sid)
        return None
    try:
        session = await oidc.refresh(session)
    except Exception:
        store.delete(sid)
        return None
    store.set(sid, session)
    return session


def _bearer(request: Request) -> str | None:
    authorization = request.headers.get("Authorization", "")
    return authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else None


async def bearer_context(request: Request) -> RequestContext | None:
    """Non-browser clients: `Authorization: Bearer <access token of the identity provider>`."""
    token = _bearer(request)
    if token is None:
        return None
    try:
        return context_from_claims(await oidc.userinfo(token), access_token=token)
    except Exception:
        return None


async def token_context(request: Request, secret: str, db: AsyncSession, limiter: RateLimiter) -> RequestContext:
    """A program with an access token of ours: who owns it, and what it may do. Never an administrator."""
    token = await AccessTokenService(AccessTokenRepository(db)).authenticate(secret)
    tokens.check_use(request, token.scope)
    if not await limiter.allow(f"token:{token.id}", settings.TOKEN_RATE_PER_MINUTE):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many calls with this token: wait a moment")
    request.state.token_id = str(token.id)  # for the log line of the call (see main.py), never the token itself
    return RequestContext(
        user_id=token.user_id,
        email=token.email,
        name=token.display_name,
        username=token.username,
        is_admin=False,  # whatever its owner is: a leaked token must not be able to moderate
        token_id=str(token.id),
        token_scope=token.scope,
    )


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> RequestContext:
    if settings.AUTH_MODE == "full-access":
        return RequestContext(user_id="dev-user", email="dev@example.com", name="Dev", roles=["admin"], is_admin=True)
    secret = _bearer(request)
    if secret is not None and tokens.looks_like_token(secret):
        # One of ours: no fallback on the session, a wrong token is simply not accepted.
        try:
            return await token_context(request, secret, db, limiter)
        except InvalidToken:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated") from None
    context = await bearer_context(request)
    if context is None and (session := await session_of(request)) is not None:
        context = context_from_claims(session.user, access_token=session.access_token)
    if context is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return context


CurrentUser = Annotated[RequestContext, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> RequestContext:
    """Dependency: the logged-in user, who must be an admin (the role is set by OIDC_ADMIN_ROLE)."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrators only")
    return user


AdminUser = Annotated[RequestContext, Depends(require_admin)]
