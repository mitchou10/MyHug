"""Access tokens: how they look, how they are kept, and what one may do.

A token is `mh_` and 43 random characters. Only its SHA-256 is stored. A token acts as its owner with the rights the
owner has on the data (looked up at every call, so taking someone off a model takes it off their tokens at once), but
it is never an administrator, a `read` token cannot change anything, and no token can manage tokens or the profile."""

import hashlib
import secrets

from fastapi import HTTPException, Request, status

PREFIX = "mh_"
SHOWN = len(PREFIX) + 8  # the first characters kept to recognise a token in a list
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# What needs a login, not a token: a stolen token must not be able to make others, nor change who the person is.
LOGIN_ONLY = ("/api/tokens", "/api/me", "/api/auth")
# POST routes that read: trying a model changes nothing.
READS_BY_POST = ("/predict",)


def generate() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def hash_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def looks_like_token(value: str) -> bool:
    return value.startswith(PREFIX)


def check_use(request: Request, scope: str) -> None:
    """Raises 403 when a token may not make this call."""
    path = request.url.path
    if any(path == prefix or path.startswith(prefix + "/") for prefix in LOGIN_ONLY):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This needs a login: an access token cannot do it")
    if scope == "read" and request.method not in SAFE_METHODS and not path.endswith(READS_BY_POST):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This token is read only")
