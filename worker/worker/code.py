"""Pinning the code of a model to a commit: the only place the worker calls a host that people named.

The address is written by users, so it is not trusted: it is checked again here against the list of hosts the worker
may call, taken apart, and **rebuilt** (the address that is called is made of the host's API and the checked parts,
never of the text that was sent). Only HTTPS, no credentials in the address, no redirect to another host, a short
timeout, a limit on the size of the answer, and a host that resolves to a private address is not called. The token of a
host goes to that host only, and is never written in a log or an error.

It reads nothing of the repository but the commit a reference points to: nothing is cloned or downloaded."""

import ipaddress
import json
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit

import httpx2

from worker.config import settings
from worker.errors import CodeProblem, HostUnavailable

_SEGMENT = re.compile(r"^(?!-)[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})$")
MAX_SEGMENTS = 6  # a GitLab allows groups in groups
MAX_REDIRECTS = 3
REDIRECTS = (301, 302, 303, 307, 308)


@dataclass(frozen=True)
class Pinned:
    sha: str


@dataclass(frozen=True)
class Unverified:
    """Not found, or private: the version keeps the link as it was written."""

    reason: str


class RateLimited(HostUnavailable):
    """The host limits the calls; `wait` is how long it asks to wait, if it says."""

    def __init__(self, wait: float | None = None) -> None:
        super().__init__("The host limits the calls")
        self.wait = wait


@dataclass(frozen=True)
class Answer:
    """What a host answered: the body is already decoded and was read within the limit."""

    status_code: int
    headers: httpx2.Headers
    content: bytes


@dataclass(frozen=True)
class Repository:
    host: str
    port: int
    project: str


def parse_repository(url: str, hosts: list[str]) -> Repository:
    """The repository the address names, or CodeProblem."""
    refusal = CodeProblem("This is not the repository of an allowed host")
    written = url.strip()
    if not written or any(ord(char) < 33 or ord(char) > 126 for char in written):
        raise refusal
    allowed: dict[str, set[int]] = {}
    for entry in hosts:
        name, _, port = entry.strip().lower().partition(":")
        allowed.setdefault(name, set()).add(int(port) if port else 443)
    try:
        parts = urlsplit(written)
        port = parts.port or 443
    except ValueError:
        raise refusal from None
    host = (parts.hostname or "").lower()
    segments = [part for part in parts.path.split("/") if part]
    if segments and segments[-1].endswith(".git"):
        segments[-1] = segments[-1][:-4]
    limit = 2 if host == "github.com" else MAX_SEGMENTS
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or "@" in parts.netloc
        or port not in allowed.get(host, set())
        or parts.query
        or parts.fragment
        or not parts.path.startswith("/")
        or "//" in parts.path
        or not 2 <= len(segments) <= limit
        or not all(_SEGMENT.match(part) and part not in (".", "..") for part in segments)
    ):
        raise refusal
    return Repository(host, port, "/".join(segments))


def public_addresses(host: str, port: int) -> list[str]:
    """What the name resolves to (the default resolver of the lookup)."""
    return [str(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


class CodeLookup:
    """Asks GitHub or a GitLab which commit a reference of a repository points to."""

    def __init__(
        self,
        *,
        hosts: list[str] | None = None,
        tokens: dict[str, str] | None = None,
        private_hosts: list[str] | None = None,
        transport: httpx2.BaseTransport | None = None,
        resolver: Callable[[str, int], list[str]] = public_addresses,
        timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self._hosts = settings.CODE_HOSTS if hosts is None else hosts
        self._tokens = {
            host.lower(): token for host, token in (settings.CODE_TOKENS if tokens is None else tokens).items()
        }
        self._private = {
            host.lower() for host in (settings.CODE_PRIVATE_HOSTS if private_hosts is None else private_hosts)
        }
        self._resolve = resolver
        self._max_bytes = max_bytes or settings.CODE_MAX_ANSWER_BYTES
        # No redirect is followed by the client: each one is looked at here (see `_get`).
        self._client = httpx2.Client(
            transport=transport, timeout=timeout or settings.CODE_TIMEOUT_SECONDS, follow_redirects=False
        )

    # ---- what is called

    @staticmethod
    def _address(repository: Repository, ref: str | None) -> tuple[str, int, str]:
        """The host and port that are called, and the path: GitHub has an API of its own, a GitLab has it on its own."""
        name = ref or "HEAD"  # the default branch
        if repository.host == "github.com":
            return "api.github.com", 443, f"/repos/{repository.project}/commits/{quote(name, safe='/')}"
        project = quote(repository.project, safe="")
        return repository.host, repository.port, f"/api/v4/projects/{project}/repository/commits/{quote(name, safe='')}"

    def _check_destination(self, repository: Repository, host: str, port: int) -> None:
        """The host must not lead to a private address: a name that is allowed can still be made to point inside."""
        if repository.host in self._private:
            return
        try:
            addresses = self._resolve(host, port)
        except OSError:
            raise HostUnavailable(f"{host} cannot be resolved") from None
        for address in addresses or ["0.0.0.0"]:  # noqa: S104
            try:
                if not ipaddress.ip_address(address.split("%")[0]).is_global:
                    raise CodeProblem(f"{host} leads to a private address")
            except ValueError:
                raise CodeProblem(f"{host} leads to an address that cannot be read") from None

    def _headers(self, repository: Repository) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "myhug-code-pinning"}
        if token := self._tokens.get(repository.host):
            headers["Authorization"] = f"Bearer {token}"  # only to the host it is for: this one
        return headers

    def _get(self, repository: Repository, host: str, port: int, path: str) -> Answer:
        """The answer, with its body read up to the limit. A redirect is followed only inside the same host."""
        url = f"https://{host}{'' if port == 443 else f':{port}'}{path}"
        for _ in range(MAX_REDIRECTS + 1):
            self._check_destination(repository, host, port)
            with self._client.stream("GET", url, headers=self._headers(repository)) as response:
                if response.status_code in REDIRECTS:
                    target = urlsplit(urljoin(url, response.headers.get("location", "")))
                    if (
                        target.scheme != "https"
                        or (target.hostname or "").lower() != host
                        or (target.port or 443) != port
                    ):
                        raise CodeProblem("The host redirects somewhere else")
                    url = target.geturl()
                    continue
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self._max_bytes:
                    raise CodeProblem("The answer of the host is too large")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise CodeProblem("The answer of the host is too large")
                return Answer(response.status_code, response.headers, bytes(body))
        raise CodeProblem("The host redirects too many times")

    # ---- the lookup

    def resolve(self, url: str, ref: str | None, kind: str = "unknown") -> Pinned | Unverified:
        """The commit `ref` points to (the default branch when there is none). Raises CodeProblem when the answer cannot
        be used, and HostUnavailable (RateLimited) when it should be asked again later."""
        repository = parse_repository(url, self._hosts)
        host, port, path = self._address(repository, ref)
        answer = self._get(repository, host, port, path)
        status = answer.status_code
        if status == 200:
            return self._commit(repository, answer, ref if kind == "commit" else None)
        if status in (404, 422):
            return Unverified("The repository or the reference was not found, or the repository is private")
        if status == 401:
            return Unverified("The repository is private")
        if status == 429 or (status == 403 and self._limited(answer)):
            raise RateLimited(self._wait(answer))
        if status == 403:
            return Unverified("Access to the repository is refused: it is private")
        if status >= 500:
            raise HostUnavailable(f"{repository.host} answered {status}")
        raise CodeProblem(f"{repository.host} answered {status}")

    @staticmethod
    def _commit(repository: Repository, answer: Answer, expected: str | None) -> Pinned:
        try:
            body = json.loads(answer.content)
            sha = body["sha"] if repository.host == "github.com" else body["id"]
        except (ValueError, KeyError, TypeError):
            raise CodeProblem(f"{repository.host} did not answer with a commit") from None
        if not isinstance(sha, str) or not _SHA.match(sha):
            raise CodeProblem(f"{repository.host} did not answer with a commit")
        if expected and expected.lower() != sha:
            raise CodeProblem(f"{repository.host} answered another commit than the one that was written")
        return Pinned(sha)

    @staticmethod
    def _limited(answer: Answer) -> bool:
        return answer.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in answer.headers

    @staticmethod
    def _wait(answer: Answer) -> float | None:
        """How long the host asks to wait, in seconds, if it says (a delay, or the moment the limit is lifted)."""
        after = answer.headers.get("retry-after", "")
        if after.isdigit():
            return float(after)
        reset = answer.headers.get("x-ratelimit-reset", "")
        if reset.isdigit():
            return max(0.0, float(reset) - time.time())
        return None
