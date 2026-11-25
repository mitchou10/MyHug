import random
from dataclasses import dataclass

# What is asked again by itself: a server that is busy or not there for a moment.
RETRY_STATUS = frozenset({429, 502, 503, 504})
# Asking again must change nothing: reading, putting, deleting. A POST is asked again only when its caller says so.
SAFE_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})
MAX_WAIT = 30.0


@dataclass(frozen=True)
class Retry:
    """How many times a call is tried again, and how long to wait: 0.5 s, 1 s, 2 s... with a little jitter, or what the
    server asks (`Retry-After`), at most `MAX_WAIT`."""

    attempts: int = 3
    base: float = 0.5

    def wait(self, attempt: int, asked: float | None = None) -> float:
        if asked is not None:
            return min(max(asked, 0.0), MAX_WAIT)
        return min(self.base * 2**attempt * random.uniform(0.8, 1.2), MAX_WAIT)  # noqa: S311


def retryable(method: str, status: int | None, *, force: bool | None) -> bool:
    """Whether a call that failed (a status, or no answer at all: `None`) may be made again."""
    if force is False or (force is None and method.upper() not in SAFE_METHODS):
        return False
    return status is None or status in RETRY_STATUS


def retry_after(header: str | None) -> float | None:
    """The delay a `Retry-After` header gives, in seconds (the date form is not used by this API)."""
    return float(header) if header and header.strip().isdigit() else None
