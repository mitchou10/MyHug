import logging
from dataclasses import dataclass
from typing import Any

from app.models import ModelEndpoint
from app.models.model_endpoint import CUSTOM, MLFLOW
from app.repositories.models import ModelRepository
from app.services.actor import Actor
from app.services.errors import BadEndpointAnswer, EndpointUnavailable, InvalidEndpoint, NoEndpoint, TooManyRequests
from app.services.model_access import ModelAccess
from app.serving import RateLimiter, ServingClient
from app.serving.addresses import check_endpoint_url, check_header, check_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EndpointView:
    """The endpoint as an editor sees it. `available` is asked of the server when the view is made, not remembered."""

    endpoint: ModelEndpoint
    available: bool | None


@dataclass(frozen=True)
class Predicted:
    output: Any
    took_ms: int


def invocation_url(endpoint: ModelEndpoint) -> str:
    """Where a request goes: an MLflow server has `/invocations`; another service says the path of its API."""
    if endpoint.kind == MLFLOW:
        return f"{endpoint.url}/invocations"
    return endpoint.url + (endpoint.api or {}).get("path", "")


def request_of(endpoint: ModelEndpoint, value: Any) -> Any:
    """What is sent to the server for an input: the protocol of MLflow, or the field the editor named."""
    if endpoint.kind == MLFLOW:
        return {"inputs": value}
    return {(endpoint.api or {}).get("input_field", "input"): value}


def output_of(endpoint: ModelEndpoint, body: Any) -> Any:
    """What the server answered, reduced to the output: `predictions` for MLflow, the path the editor gave for another
    service (`predictions.0.label`: keys, and numbers for the places in a list; empty: all of it)."""
    if endpoint.kind == MLFLOW:
        return body["predictions"] if isinstance(body, dict) and "predictions" in body else body
    found: Any = body
    for step in filter(None, (endpoint.api or {}).get("output_path", "").split(".")):
        try:
            found = found[int(step)] if isinstance(found, list) else found[step]
        except (KeyError, IndexError, ValueError, TypeError):
            raise BadEndpointAnswer("The answer of the model does not have the output that was described") from None
    return found


class ModelServingService:
    """Where a model can be tried, and the relay to it.

    The platform does not run models. A model is served **only when somebody says where**: an editor sets the endpoint
    (an MLflow model server that answers, or a service of their own whose API they describe), and without one there is
    nothing to try (409). The address is only ever shown to the editors; a reader sends their input to the relay and
    gets the output, and never learns where it went."""

    def __init__(
        self,
        models: ModelRepository,
        access: ModelAccess,
        client: ServingClient,
        limiter: RateLimiter,
        *,
        origins: list[str],
        rate_per_minute: int,
    ) -> None:
        self._models = models
        self._access = access
        self._client = client
        self._limiter = limiter
        self._origins = origins
        self._rate = rate_per_minute

    @staticmethod
    def _header(endpoint: ModelEndpoint) -> tuple[str, str] | None:
        return (endpoint.auth_header, endpoint.auth_value) if endpoint.auth_header and endpoint.auth_value else None

    async def _view(self, endpoint: ModelEndpoint) -> EndpointView:
        available = await self._client.ping(endpoint.url, self._header(endpoint)) if endpoint.kind == MLFLOW else None
        return EndpointView(endpoint, available)

    async def get(self, actor: Actor, owner: str, name: str) -> EndpointView:
        """For the editors. Raises NoEndpoint when there is none."""
        model = await self._access.get_editable(actor, owner, name)
        endpoint = await self._models.get_endpoint(model.id)
        if endpoint is None:
            raise NoEndpoint
        return await self._view(endpoint)

    async def set(self, actor: Actor, owner: str, name: str, data: dict[str, Any]) -> EndpointView:
        """Sets where the model is served (replacing what was there). Raises InvalidEndpoint for an address that is not
        on the allowlist, a path or a header that is not accepted; and EndpointUnavailable for an MLflow server that
        does not answer: a model is only declared served when it is there."""
        model = await self._access.get_editable(actor, owner, name)
        kind = data["kind"]
        url = check_endpoint_url(data["url"], self._origins)
        api = data.get("api")
        if kind == CUSTOM:
            if not api:
                raise InvalidEndpoint("Describe the API of this service: its path and the field of the input")
            api = {**api, "path": check_path(api["path"])}
        elif api:
            raise InvalidEndpoint("An MLflow server has the same API everywhere: there is nothing to describe")
        previous = await self._models.get_endpoint(model.id)
        header, value = data.get("auth_header"), data.get("auth_value")
        if header:
            check_header(header)
            if value is None and previous and previous.auth_header == header:
                value = previous.auth_value  # the secret is never read back: sending the header alone keeps it
            if not value:
                raise InvalidEndpoint("A header needs a value")
        elif value:
            raise InvalidEndpoint("A value needs the name of its header")
        if kind == MLFLOW and not await self._client.ping(url, (header, value) if header and value else None):
            raise EndpointUnavailable("This MLflow server does not answer: the model is served when it is there")
        await self._models.set_endpoint(
            model.id,
            actor.user_id,
            kind=kind,
            url=url,
            alias=data.get("alias"),
            input_kind=data["input_kind"],
            output_kind=data["output_kind"],
            api=api,
            auth_header=header or None,
            auth_value=value or None,
        )
        await self._models.commit()
        endpoint = await self._models.get_endpoint(model.id)
        assert endpoint is not None
        return await self._view(endpoint)

    async def delete(self, actor: Actor, owner: str, name: str) -> None:
        model = await self._access.get_editable(actor, owner, name)
        if not await self._models.delete_endpoint(model.id):
            raise NoEndpoint
        await self._models.commit()

    async def predict(self, actor: Actor, owner: str, name: str, value: Any) -> Predicted:
        """Sends an input to the server of the model and returns its output. Raises NoEndpoint (nothing to try),
        TooManyRequests, and what the server does: EndpointUnavailable, EndpointTimeout, InputRejected,
        BadEndpointAnswer."""
        model, _ = await self._access.get_readable(actor, owner, name)
        endpoint = await self._models.get_endpoint(model.id)
        if endpoint is None:
            raise NoEndpoint
        if not await self._limiter.allow(f"predict:{actor.user_id}", self._rate):
            raise TooManyRequests
        prediction = await self._client.call(
            invocation_url(endpoint), request_of(endpoint, value), self._header(endpoint)
        )
        return Predicted(output_of(endpoint, prediction.body), prediction.took_ms)
