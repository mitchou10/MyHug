"""What the two clients (blocking and asyncio) share: how an answer becomes a result or an exception."""

from typing import Any

import httpx2

from myhug import errors
from myhug._retry import retry_after

USER_AGENT = "myhug-sdk"
DETAIL_LIMIT = 300

_BY_STATUS: dict[int, type[errors.ApiError]] = {
    401: errors.AuthenticationError,
    403: errors.PermissionDenied,
    404: errors.NotFound,
    409: errors.Conflict,
    413: errors.TooLarge,
    422: errors.Invalid,
}


def detail_of(response: httpx2.Response) -> str:
    """The sentence of the API: a string, or the list of problems of a wrong request, kept short. A body that is not
    what the API sends (a proxy's page) is not echoed."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.reason_phrase or "error"
    if isinstance(detail, list):
        detail = "; ".join(
            f"{'.'.join(str(p) for p in item.get('loc', [])[1:])}: {item.get('msg', '')}".strip(": ")
            for item in detail
            if isinstance(item, dict)
        )
    return str(detail)[:DETAIL_LIMIT] if detail else response.reason_phrase or "error"


def error_of(response: httpx2.Response) -> errors.ApiError:
    status, detail = response.status_code, detail_of(response)
    if status == 429:
        return errors.RateLimited(status, detail, retry_after(response.headers.get("retry-after")))
    if status >= 500:
        return errors.ServerError(status, detail)
    return _BY_STATUS.get(status, errors.ApiError)(status, detail)


def result_of(response: httpx2.Response) -> Any:
    """The JSON of a successful answer (nothing for a 204), or the exception of a failed one."""
    if response.is_error:
        raise error_of(response)
    return None if response.status_code == 204 or not response.content else response.json()


def clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """The parameters that are set: a filter left empty is not sent."""
    return {k: v for k, v in params.items() if v is not None} if params else None
