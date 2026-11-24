"""Pinning the code of a model: what the worker may call, and what it makes of the answers."""

import json
import logging

import httpx2
import pytest

from worker.code import CodeLookup, Pinned, RateLimited, Unverified, parse_repository
from worker.errors import CodeProblem, HostUnavailable

SHA = "a" * 40
PUBLIC = ["140.82.112.3"]


class Host:
    """The answers of the hosts, in turn, and the requests they got."""

    def __init__(self, *answers: httpx2.Response) -> None:
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.answers.pop(0) if self.answers else httpx2.Response(500)

    @property
    def last(self) -> httpx2.Request:
        return self.requests[-1]


def github(sha: str = SHA) -> httpx2.Response:
    return httpx2.Response(200, json={"sha": sha, "commit": {}})


def gitlab(sha: str = SHA) -> httpx2.Response:
    return httpx2.Response(200, json={"id": sha, "short_id": sha[:8]})


def lookup(host: Host, **options) -> CodeLookup:
    options.setdefault("resolver", lambda name, port: PUBLIC)
    options.setdefault("hosts", ["github.com", "gitlab.com", "git.example.org:8443"])
    options.setdefault("tokens", {})
    options.setdefault("private_hosts", [])
    return CodeLookup(transport=httpx2.MockTransport(host), **options)


# ---- what is asked


def test_a_reference_of_github_is_asked_to_the_api_of_github() -> None:
    host = Host(github())
    assert lookup(host).resolve("https://github.com/ada/sentiment", "v1.0") == Pinned(SHA)
    assert str(host.last.url) == "https://api.github.com/repos/ada/sentiment/commits/v1.0"
    assert host.last.method == "GET"


def test_a_reference_of_a_gitlab_is_asked_to_that_gitlab_with_the_project_in_one_piece() -> None:
    host = Host(gitlab())
    lookup(host).resolve("https://gitlab.com/group/sub/project.git", "main")
    assert str(host.last.url) == "https://gitlab.com/api/v4/projects/group%2Fsub%2Fproject/repository/commits/main"


def test_a_gitlab_on_another_port_is_called_on_that_port() -> None:
    host = Host(gitlab())
    lookup(host).resolve("https://git.example.org:8443/team/model", "main")
    assert str(host.last.url).startswith("https://git.example.org:8443/api/v4/projects/team%2Fmodel/")


def test_a_branch_with_a_slash_is_written_the_way_each_host_wants() -> None:
    host = Host(github(), gitlab())
    lookup(host).resolve("https://github.com/ada/x", "feature/new")
    assert host.last.url.path == "/repos/ada/x/commits/feature/new"
    lookup(host).resolve("https://gitlab.com/ada/x", "feature/new")
    assert host.last.url.raw_path.decode().endswith("/commits/feature%2Fnew")


def test_without_a_reference_the_default_branch_is_asked() -> None:
    host = Host(github())
    lookup(host).resolve("https://github.com/ada/x", None)
    assert host.last.url.path.endswith("/commits/HEAD")


def test_the_answer_of_a_gitlab_is_read_in_its_own_field() -> None:
    assert lookup(Host(gitlab("b" * 64))).resolve("https://gitlab.com/ada/x", "main") == Pinned("b" * 64)


def test_a_commit_that_was_written_must_be_the_one_that_is_answered() -> None:
    assert lookup(Host(github())).resolve("https://github.com/ada/x", SHA.upper(), "commit") == Pinned(SHA)
    with pytest.raises(CodeProblem, match="another commit"):
        lookup(Host(github("b" * 40))).resolve("https://github.com/ada/x", SHA, "commit")


# ---- what the host answers


@pytest.mark.parametrize("status", [404, 422, 401])
def test_a_repository_or_reference_that_is_not_found_is_not_verified(status: int) -> None:
    answer = lookup(Host(httpx2.Response(status))).resolve("https://github.com/ada/x", "v1")
    assert isinstance(answer, Unverified) and answer.reason


def test_an_access_that_is_refused_is_a_private_repository() -> None:
    assert isinstance(lookup(Host(httpx2.Response(403))).resolve("https://github.com/ada/x", "v1"), Unverified)


def test_a_rate_limit_is_to_be_asked_again_later() -> None:
    limited = httpx2.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"})
    with pytest.raises(RateLimited) as caught:
        lookup(Host(limited)).resolve("https://github.com/ada/x", "v1")
    assert caught.value.wait is not None and caught.value.wait > 0
    with pytest.raises(RateLimited) as caught:
        lookup(Host(httpx2.Response(429, headers={"retry-after": "42"}))).resolve("https://github.com/ada/x", "v1")
    assert caught.value.wait == 42
    with pytest.raises(RateLimited) as caught:
        lookup(Host(httpx2.Response(429))).resolve("https://gitlab.com/ada/x", "v1")
    assert caught.value.wait is None


def test_a_host_that_is_down_is_to_be_asked_again_later() -> None:
    with pytest.raises(HostUnavailable):
        lookup(Host(httpx2.Response(503))).resolve("https://github.com/ada/x", "v1")


def test_a_host_that_does_not_answer_is_an_error_of_the_job_not_of_the_version() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("slow")

    with pytest.raises(httpx2.HTTPError):
        CodeLookup(
            transport=httpx2.MockTransport(down), resolver=lambda *_: PUBLIC, tokens={}, private_hosts=[]
        ).resolve("https://github.com/ada/x", "v1")


def test_an_answer_that_cannot_be_used_fails() -> None:
    for answer in (
        httpx2.Response(418),
        httpx2.Response(200, content=b"<html>"),
        httpx2.Response(200, json={"nothing": 1}),
        httpx2.Response(200, json={"sha": "not-a-sha"}),
        httpx2.Response(200, json={"sha": 12}),
        httpx2.Response(200, json=[1, 2]),
    ):
        with pytest.raises(CodeProblem):
            lookup(Host(answer)).resolve("https://github.com/ada/x", "v1")


# ---- what is never called


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/ada/x",
        "https://user:pw@github.com/ada/x",
        "https://ada@github.com/ada/x",
        "https://127.0.0.1/ada/x",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/ada/x",
        "https://localhost/ada/x",
        "https://github.com:8443/ada/x",
        "https://github.com./ada/x",
        "https://gitlab.com:444/ada/x",
        "https://evil.example/ada/x",
        "https://github.com.evil.example/ada/x",
        "https://github.com/ada/../x",
        "https://github.com/ada/x?x=1",
        "https://github.com/ada/x/tree/main",
        "https://gitlab.com/ada/x/-/tree/main",
        "https://github.com/ada",
        "file:///etc/passwd",
        "",
    ],
)
def test_an_address_that_is_not_a_repository_of_an_allowed_host_is_not_called(url: str) -> None:
    host = Host(github())
    with pytest.raises(CodeProblem):
        lookup(host).resolve(url, "main")
    assert host.requests == []  # nothing left the worker


def test_the_list_of_hosts_is_the_one_of_the_worker_not_the_one_of_the_address() -> None:
    host = Host(github())
    with pytest.raises(CodeProblem):
        lookup(host, hosts=["gitlab.com"]).resolve("https://github.com/ada/x", "main")
    assert host.requests == []


@pytest.mark.parametrize(
    "address", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1", "172.16.0.9", "::1", "fd00::1"]
)
def test_a_host_that_leads_to_a_private_address_is_not_called(address: str) -> None:
    host = Host(github())
    with pytest.raises(CodeProblem, match="private"):
        lookup(host, resolver=lambda name, port: [address]).resolve("https://github.com/ada/x", "main")
    assert host.requests == []


def test_one_private_address_among_public_ones_is_enough_to_refuse() -> None:
    host = Host(github())
    with pytest.raises(CodeProblem):
        lookup(host, resolver=lambda name, port: ["140.82.112.3", "10.0.0.1"]).resolve("https://github.com/ada/x", "m")
    assert host.requests == []


def test_a_gitlab_inside_the_network_is_called_only_when_it_is_named() -> None:
    inside = lambda name, port: ["10.1.2.3"]  # noqa: E731
    with pytest.raises(CodeProblem):
        lookup(Host(gitlab()), resolver=inside).resolve("https://gitlab.com/ada/x", "main")
    assert lookup(Host(gitlab()), resolver=inside, private_hosts=["gitlab.com"]).resolve(
        "https://gitlab.com/ada/x", "main"
    ) == Pinned(SHA)


def test_a_name_that_cannot_be_resolved_is_to_be_asked_again_later() -> None:
    def broken(name: str, port: int) -> list[str]:
        raise OSError("no such host")

    with pytest.raises(HostUnavailable):
        lookup(Host(github()), resolver=broken).resolve("https://github.com/ada/x", "main")


# ---- redirects


def test_a_redirect_inside_the_same_host_is_followed() -> None:
    host = Host(
        httpx2.Response(301, headers={"location": "https://api.github.com/repositories/42/commits/v1"}), github()
    )
    assert lookup(host).resolve("https://github.com/ada/x", "v1") == Pinned(SHA)
    assert str(host.last.url) == "https://api.github.com/repositories/42/commits/v1"


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data",
        "https://169.254.169.254/latest/meta-data",
        "https://evil.example/steal",
        "https://api.github.com.evil.example/x",
        "http://api.github.com/repositories/42",  # the same host, but not https
        "https://api.github.com:8443/repositories/42",  # the same host, another port
        "//evil.example/x",
        "ftp://api.github.com/x",
    ],
)
def test_a_redirect_to_another_place_is_refused_and_not_followed(location: str) -> None:
    host = Host(httpx2.Response(302, headers={"location": location}), github())
    with pytest.raises(CodeProblem, match="redirects"):
        lookup(host).resolve("https://github.com/ada/x", "v1")
    assert len(host.requests) == 1  # it never went there


def test_a_redirect_that_never_ends_is_given_up() -> None:
    loop = httpx2.Response(302, headers={"location": "https://api.github.com/again"})
    host = Host(*[loop] * 10)
    with pytest.raises(CodeProblem, match="too many"):
        lookup(host).resolve("https://github.com/ada/x", "v1")
    assert len(host.requests) <= 4


# ---- the size of the answer


def test_an_answer_that_declares_itself_too_large_is_refused() -> None:
    big = httpx2.Response(200, headers={"content-length": "999999999"}, content=b"{}")
    with pytest.raises(CodeProblem, match="too large"):
        lookup(Host(big)).resolve("https://github.com/ada/x", "v1")


def test_an_answer_that_turns_out_too_large_is_cut() -> None:
    body = json.dumps({"sha": SHA, "pad": "x" * 5000}).encode()
    with pytest.raises(CodeProblem, match="too large"):
        lookup(Host(httpx2.Response(200, content=body)), max_bytes=1000).resolve("https://github.com/ada/x", "v1")


# ---- the tokens


def test_the_token_of_a_host_goes_to_that_host_only() -> None:
    host = Host(github(), gitlab())
    tokens = {"github.com": "ghp_SECRET_ONE", "gitlab.com": "glpat_SECRET_TWO"}
    lookup(host, tokens=tokens).resolve("https://github.com/ada/x", "v1")
    assert host.last.headers["authorization"] == "Bearer ghp_SECRET_ONE"
    lookup(host, tokens=tokens).resolve("https://gitlab.com/ada/x", "v1")
    assert host.last.headers["authorization"] == "Bearer glpat_SECRET_TWO"


def test_a_host_without_a_token_gets_none() -> None:
    host = Host(gitlab())
    lookup(host, tokens={"github.com": "ghp_SECRET_ONE"}).resolve("https://gitlab.com/ada/x", "v1")
    assert "authorization" not in host.last.headers


def test_a_token_is_never_in_an_error_or_a_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    tokens = {"github.com": "ghp_SECRET_ONE"}
    for answer in (httpx2.Response(418), httpx2.Response(200, content=b"nope"), httpx2.Response(503)):
        with pytest.raises((CodeProblem, HostUnavailable)) as caught:
            lookup(Host(answer), tokens=tokens).resolve("https://github.com/ada/x", "v1")
        assert "SECRET" not in str(caught.value)
    assert "SECRET" not in caplog.text


def test_the_token_is_not_sent_to_where_a_redirect_would_lead() -> None:
    host = Host(httpx2.Response(302, headers={"location": "https://evil.example/x"}), github())
    with pytest.raises(CodeProblem):
        lookup(host, tokens={"github.com": "ghp_SECRET_ONE"}).resolve("https://github.com/ada/x", "v1")
    assert [r.url.host for r in host.requests] == ["api.github.com"]  # the one request that carried it


def test_the_parts_of_an_address_are_checked_the_same_way_here_as_in_the_api() -> None:
    assert parse_repository("https://gitlab.com/g/s/p.git", ["gitlab.com"]).project == "g/s/p"
    with pytest.raises(CodeProblem):
        parse_repository("https://gitlab.com/g/s/p/-/tree/x", ["gitlab.com"])


def test_a_compressed_answer_is_read() -> None:
    """The hosts compress their answers: the body is decoded once, and what is kept is the plain text."""
    import gzip

    body = gzip.compress(json.dumps({"sha": SHA}).encode())
    answer = httpx2.Response(200, headers={"content-encoding": "gzip"}, content=body)
    assert lookup(Host(answer)).resolve("https://github.com/ada/x", "v1") == Pinned(SHA)
