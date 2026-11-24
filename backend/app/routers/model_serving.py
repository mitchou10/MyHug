from fastapi import APIRouter, Request, Response, status

from app.config import settings
from app.routers.deps import ActorDep, ModelServingDep
from app.schemas import EndpointIn, EndpointOut, PredictIn, PredictOut
from app.services.errors import InputRejected, InputTooLarge

router = APIRouter(prefix="/api/models/{owner}/{name}", tags=["model serving"])


async def read_limited(request: Request, limit: int) -> bytes:
    """The body of a request, read as it comes and refused as soon as it passes the limit: a huge body is never held."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise InputTooLarge
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise InputTooLarge
    return bytes(body)


@router.get("/endpoint", summary="Where a model is served (for the people who can edit it)")
async def get_endpoint(owner: str, name: str, actor: ActorDep, service: ModelServingDep) -> EndpointOut:
    return EndpointOut.from_view(await service.get(actor, owner, name))


@router.put(
    "/endpoint",
    summary="Say where a model is served: an MLflow server that answers, or a service with its API described",
)
async def set_endpoint(
    owner: str, name: str, data: EndpointIn, actor: ActorDep, service: ModelServingDep
) -> EndpointOut:
    return EndpointOut.from_view(await service.set(actor, owner, name, data.model_dump()))


@router.delete("/endpoint", status_code=status.HTTP_204_NO_CONTENT, summary="The model is not served any more")
async def delete_endpoint(owner: str, name: str, actor: ActorDep, service: ModelServingDep) -> Response:
    await service.delete(actor, owner, name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/predict",
    summary="Try a model: the input goes to the server that serves it, the output comes back",
    description="Everybody who can read the model may try it. The address of the server is never given. "
    "409: the model is not served. 503: its server does not answer. 504: it took too long. 413: more than 1 MiB. "
    "429: too many tries.",
)
async def predict(owner: str, name: str, request: Request, actor: ActorDep, service: ModelServingDep) -> PredictOut:
    raw = await read_limited(request, settings.SERVING_MAX_BODY_BYTES)
    try:
        data = PredictIn.model_validate_json(raw)
    except ValueError:
        raise InputRejected("Send a JSON object with an `input`") from None
    predicted = await service.predict(actor, owner, name, data.input)
    return PredictOut(output=predicted.output, took_ms=predicted.took_ms)
