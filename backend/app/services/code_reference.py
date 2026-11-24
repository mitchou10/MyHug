"""The code a version of a model points to: a repository on one of the allowed hosts, and where to start in it.

Nothing here (or anywhere in the API) fetches the address or clones it: it is only checked, kept, and shown. A worker
pins it to a commit later. The rules are strict because a machine will follow the address, not a person:
https only, no credentials, a host of the allowlist (so no IP address, no `localhost`, no internal name), the default
port, and a path of exactly `/{owner}/{repository}`."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.models.model_version import CODE_REF_KINDS, COMMIT, UNKNOWN
from app.services.errors import InvalidCodeReference, InvalidFilePath
from app.services.paths import clean_path

_REPOSITORY = re.compile(r"^/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
_COMMIT = re.compile(r"^([0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


@dataclass(frozen=True)
class CodeReference:
    """What the author wrote, checked."""

    url: str
    ref: str | None = None
    ref_kind: str = UNKNOWN
    path: str | None = None
    entrypoint: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "url": self.url,
            "ref": self.ref,
            "ref_kind": self.ref_kind,
            "path": self.path,
            "entrypoint": self.entrypoint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CodeReference":
        return cls(
            data["url"], data.get("ref"), data.get("ref_kind") or UNKNOWN, data.get("path"), data.get("entrypoint")
        )


def check_repository_url(url: str, hosts: list[str]) -> str:
    """The address, as written (without the spaces around it), if it is the repository of an allowed host."""
    written = url.strip()
    refusal = InvalidCodeReference(
        "The code must be a repository, `https://{host}/{owner}/{repository}`, on an allowed host"
    )
    if not written or any(ord(char) < 33 or ord(char) > 126 for char in written):  # spaces, control and non-ASCII
        raise refusal
    try:
        parts = urlsplit(written)
        port = parts.port
    except ValueError:
        raise refusal from None
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or host not in {allowed.lower() for allowed in hosts}
        or parts.query
        or parts.fragment
        or "@" in parts.netloc
        or not _REPOSITORY.match(parts.path)
        or any(part in (".", "..") for part in parts.path.split("/"))
    ):
        raise refusal
    return written


def check_code_reference(
    url: str,
    *,
    ref: str | None = None,
    ref_kind: str | None = None,
    path: str | None = None,
    entrypoint: str | None = None,
    hosts: list[str],
) -> CodeReference:
    """Raises InvalidCodeReference for whatever is not accepted."""
    checked = check_repository_url(url, hosts)
    ref = ref.strip() if ref else None
    if ref is not None:
        if not _REF.match(ref) or ".." in ref or "//" in ref or ref.endswith(("/", ".lock", ".")):
            raise InvalidCodeReference("This branch, tag or commit is not accepted")
        kind = ref_kind or (COMMIT if _COMMIT.match(ref) else UNKNOWN)
        if kind not in CODE_REF_KINDS:
            raise InvalidCodeReference("The kind of reference must be commit, tag, branch or unknown")
        if kind == COMMIT and not _COMMIT.match(ref):
            raise InvalidCodeReference("A commit is 40 or 64 hexadecimal characters")
    else:
        if ref_kind not in (None, UNKNOWN):
            raise InvalidCodeReference("Give the reference that this kind is about")
        kind = UNKNOWN
    return CodeReference(checked, ref, kind, _folder(path, "path"), _folder(entrypoint, "entrypoint"))


def _folder(value: str | None, what: str) -> str | None:
    if value is None or not value.strip():
        return None
    if value.strip().startswith(("/", "\\")):
        raise InvalidCodeReference(f"The {what} must be relative to the repository, not start with a slash")
    try:
        return clean_path(value)
    except InvalidFilePath:
        raise InvalidCodeReference(f"The {what} must be a relative path, without `..`") from None
