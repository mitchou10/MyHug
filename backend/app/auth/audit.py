import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.tokens")


class TokenCallLog:
    """One log line for each call made with an access token: which token, what, and how it went. Never the token.

    Plain ASGI (not `BaseHTTPMiddleware`): the body of a request and of an answer go through untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 0

        async def watching(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, watching)
        finally:
            # `request.state` is `scope["state"]`: the dependency that accepted the token put its id there.
            if token_id := scope.get("state", {}).get("token_id"):
                logger.info("token=%s %s %s -> %s", token_id, scope["method"], scope["path"], status)
