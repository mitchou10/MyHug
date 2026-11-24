"""The address of an endpoint: what an editor may make the backend call.

The backend calls what editors write, so this is the one defence against making it call an internal address: only an
origin (scheme, host and port) that the administrators listed in `MODEL_SERVING_ORIGINS` is accepted, exactly, and it is
checked again at every call (the list can change). No credentials, no query, no fragment, no `..`; nothing is ever
followed to another place (a redirect is an error)."""

import re
from urllib.parse import urlsplit

from app.services.errors import InvalidEndpoint

_PATH = re.compile(r"^(/[A-Za-z0-9._~!$&'()*+,;=:@%-]*)*$")
_HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,99}$")
# What the platform sets itself, or what would change where the request goes.
_FORBIDDEN_HEADERS = {
    "host",
    "content-length",
    "content-type",
    "transfer-encoding",
    "connection",
    "upgrade",
    "te",
    "trailer",
    "expect",
    "proxy-authorization",
    "proxy-connection",
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
}


def origin_of(url: str) -> str:
    """`scheme://host[:port]`, in lowercase, with the default port left out. Raises InvalidEndpoint."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise InvalidEndpoint("This is not an address") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidEndpoint("The endpoint must be an http or https address")
    host = parts.hostname.lower()
    if ":" in host:  # an IPv6 address
        host = f"[{host}]"
    default = 443 if parts.scheme == "https" else 80
    return f"{parts.scheme}://{host}" + (f":{port}" if port not in (None, default) else "")


def check_endpoint_url(url: str, origins: list[str]) -> str:
    """The address, without a slash at its end, if it is on an allowed origin. Raises InvalidEndpoint."""
    written = url.strip()
    if not written or any(ord(char) < 33 or ord(char) > 126 for char in written):
        raise InvalidEndpoint("This is not an address")
    parts = urlsplit(written)
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise InvalidEndpoint("An address with a login is not accepted: use the header of the endpoint")
    if parts.query or parts.fragment or ".." in parts.path.split("/") or "//" in parts.path:
        raise InvalidEndpoint("The address must have no query, no fragment and no `..`")
    if not _PATH.match(parts.path):
        raise InvalidEndpoint("The path of the address has characters that are not accepted")
    allowed = {origin_of(origin) for origin in origins}
    if origin_of(written) not in allowed:
        raise InvalidEndpoint("This server is not one that models may be served from")
    return written.rstrip("/")


def check_path(path: str) -> str:
    """A path of the API of a service, relative to the address of the endpoint. Raises InvalidEndpoint."""
    if not path.startswith("/") or "//" in path or ".." in path.split("/") or not _PATH.match(path):
        raise InvalidEndpoint("The path of the API must start with a slash and have no `..`, query or fragment")
    return path


def check_header(name: str) -> str:
    if not _HEADER.match(name) or name.lower() in _FORBIDDEN_HEADERS:
        raise InvalidEndpoint("This header cannot be used for the login of an endpoint")
    return name
