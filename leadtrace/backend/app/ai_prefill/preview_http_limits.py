"""Bound Preview assistance bodies before parsing, authentication or writes."""
from __future__ import annotations

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import _error_response


MAX_PREVIEW_REQUEST_BYTES = 2 * 1024 * 1024
_ASSISTANCE_PREFIX = "/api/v2/admin/ai-prefill"


class PreviewRequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or scope.get("method", "GET") in {"GET", "HEAD", "OPTIONS"}
            or not (path == _ASSISTANCE_PREFIX or path.startswith(_ASSISTANCE_PREFIX + "/"))
        ):
            await self.app(scope, receive, send)
            return

        async def reject() -> None:
            response = _error_response(
                Request(scope), status_code=413, code="PREVIEW_REQUEST_TOO_LARGE",
                message="Preview assistance request body exceeds 2 MiB",
                details={"max_bytes": MAX_PREVIEW_REQUEST_BYTES},
            )
            await response(scope, receive, send)

        # A large declared size can fail immediately, but a missing, invalid or
        # understated header never bypasses the actual streamed-byte count.
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    continue
                if declared > MAX_PREVIEW_REQUEST_BYTES:
                    await reject()
                    return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_PREVIEW_REQUEST_BYTES:
                await reject()
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        # Downstream parsing receives exactly the bytes that passed the limit.
        # No endpoint or dependency executes while a partial upload is pending.
        complete = bytes(body)
        delivered = False

        async def buffered_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": complete, "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)
