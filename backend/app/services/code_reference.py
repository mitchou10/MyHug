"""The code a version of a model points to: a repository on one of the allowed hosts, and where to start in it.

Nothing here (or anywhere in the API) fetches the address or clones it: it is only checked, kept, and shown. A worker
pins it to a commit later. The rules are strict because a machine will follow the address, not a person:
https only, no credentials, a host of the allowlist (so no IP address, no `localhost`, no internal name),
the port of its entry (443 unless the entry says `host:port`), and a path of exactly `/{owner}/{repository}`
(a GitLab also allows groups in groups)."""

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from app.models.model_version import CODE_REF_KINDS, COMMIT, UNKNOWN
from app.services.errors import InvalidCodeReference, InvalidFilePath
from app.services.paths import clean_path

_SEGMENT = re.compile(r"^(?!-)[A-Za-z0-9_.-]+$")  # not `-`: a GitLab puts `/-/` before its own pages
MAX_GROUPS = 4  # a GitLab allows groups in groups: `group/sub/sub/repository`
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


@dataclass(frozen=True)
class Repository:
    """The parts of a repository address that were checked."""

    host: str
    port: int
    segments: tuple[str, ...]

    @property
    def project(self) -> str:
        """`owner/repository` (GitLab: `group/subgroup/repository`), without a `.git` at the end."""
        return "/".join(self.segments)


def _allowed_ports(hosts: list[str]) -> dict[str, set[int]]:
    """`github.com` is allowed on 443; `git.example.org:8443` on 8443 (and only there)."""
    allowed: dict[str, set[int]] = {}
    for entry in hosts:
        host, _, port = entry.strip().lower().partition(":")
        allowed.setdefault(host, set()).add(int(port) if port else 443)
    return allowed


def parse_repository(url: str, hosts: list[str]) -> Repository:
    """The repository the address names. Raises InvalidCodeReference for what is not a repository of an allowed host.
    GitHub has `/{owner}/{repository}`, a GitLab (any other host) allows groups inside groups."""
    refusal = InvalidCodeReference(
        "The code must be a repository, `https://{host}/{owner}/{repository}`, on an allowed host"
    )
    written = url.strip()
    if not written or any(ord(char) < 33 or ord(char) > 126 for char in written):  # spaces, control and non-ASCII
        raise refusal
    try:
        parts = urlsplit(written)
        port = parts.port or 443
    except ValueError:
        raise refusal from None
    host = (parts.hostname or "").lower()  # a trailing dot (`github.com.`) is another name: it is not in the list
    segments = [part for part in parts.path.split("/") if part]
    if segments and segments[-1].endswith(".git"):
        segments[-1] = segments[-1][:-4]
    limit = 2 if host == "github.com" else MAX_GROUPS + 2
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or "@" in parts.netloc
        or port not in _allowed_ports(hosts).get(host, set())
        or parts.query
        or parts.fragment
        or not parts.path.startswith("/")
        or "//" in parts.path
        or not 2 <= len(segments) <= limit
        or not all(_SEGMENT.match(part) and part not in (".", "..") for part in segments)
    ):
        raise refusal
    return Repository(host, port, tuple(segments))


def check_repository_url(url: str, hosts: list[str]) -> str:
    """The address, as written (without the spaces around it), if it is the repository of an allowed host."""
    parse_repository(url, hosts)
    return url.strip()


def tree_url(url: str, sha: str, path: str | None, hosts: list[str]) -> str | None:
    """The page of the code at the exact commit (and the folder), built from the checked parts; None if the address is
    not one of an allowed host (the list changed since)."""
    try:
        repository = parse_repository(url, hosts)
    except InvalidCodeReference:
        return None
    port = "" if repository.port == 443 else f":{repository.port}"
    marker = "tree" if repository.host == "github.com" else "-/tree"
    folder = f"/{quote(path, safe='/')}" if path else ""
    return f"https://{repository.host}{port}/{repository.project}/{marker}/{sha}{folder}"


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
