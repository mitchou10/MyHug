"""What goes wrong, as exceptions. None of them holds the token, a header or a signed address."""


class MyHugError(Exception):
    """Base of every error of the SDK."""


class ConnectionFailed(MyHugError):
    """The server could not be reached (network down, timeout), after the attempts the client makes."""


class InsecureUrl(MyHugError):
    """A token must not travel over plain HTTP, except to this machine."""


class ApiError(MyHugError):
    """The API answered with an error: the status code, and the sentence it gave."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class AuthenticationError(ApiError):
    """401: no token, a wrong one, a revoked one, an expired one (the API does not say which)."""


class PermissionDenied(ApiError):
    """403: the token may not do this (a read token that writes, a call that needs a login)."""


class NotFound(ApiError):
    """404: it does not exist, or it is private and not yours (the API does not say which)."""


class Conflict(ApiError):
    """409: a name that is taken, a version that is not ready..."""


class TooLarge(ApiError):
    """413."""


class Invalid(ApiError):
    """422: something is missing or not valid."""


class RateLimited(ApiError):
    """429: `retry_after` is how long the server asks to wait, in seconds, when it says."""

    def __init__(self, status_code: int, detail: str, retry_after: float | None = None) -> None:
        super().__init__(status_code, detail)
        self.retry_after = retry_after


class ServerError(ApiError):
    """5xx."""


class IntegrityError(MyHugError):
    """What was downloaded is not what the platform holds (its size or its fingerprint differs): it is not kept."""


class UploadError(MyHugError):
    """An upload could not be finished. What reached the storage is kept: running it again goes on from there."""


class FileChanged(UploadError):
    """A file is not the one that was announced (it changed since): nothing more is sent."""


class VersionFailed(MyHugError):
    """A version could not be read by the platform (`reason` says why): its files are not usable."""

    def __init__(self, number: int, reason: str | None) -> None:
        super().__init__(f"Version {number} failed: {reason or 'no reason given'}")
        self.number = number
        self.reason = reason


class WaitTimeout(MyHugError):
    """A version is still being read after the time that was given."""


class UnsupportedFormat(MyHugError):
    """The rows of this kind of file cannot be read here (csv, tsv, jsonl and parquet can)."""


class MissingDependency(MyHugError):
    """Something optional is needed: `pip install "myhug[parquet]"`."""


class UnreadableRows(MyHugError):
    """A file does not hold what its name says (not UTF-8, a line that is not a JSON object...)."""
