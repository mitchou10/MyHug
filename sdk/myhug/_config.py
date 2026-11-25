import os
from urllib.parse import urlsplit

from myhug.errors import InsecureUrl, MyHugError

DEFAULT_URL = "http://localhost:8000"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def resolve(url: str | None, token: str | None, *, allow_insecure: bool) -> tuple[str, str | None]:
    """The address and the token: what is given, else `MYHUG_URL` and `MYHUG_TOKEN`. A token is only sent over HTTPS (or
    to this machine): anyone on the way would read it otherwise."""
    address = (url or os.environ.get("MYHUG_URL") or DEFAULT_URL).rstrip("/")
    secret = token or os.environ.get("MYHUG_TOKEN") or None
    parts = urlsplit(address)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise MyHugError(f"Not an address: {address!r}")
    if parts.username or parts.password:
        raise MyHugError("Put the token in `token`, not in the address")
    if secret and parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS and not allow_insecure:
        raise InsecureUrl("The token would go over plain HTTP: use https, or allow_insecure=True for a trusted network")
    return address, secret
