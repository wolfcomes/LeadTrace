from __future__ import annotations

from typing import BinaryIO

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


class SnapshotStreamingResponse(StreamingResponse):
    """Close a verified snapshot when the complete ASGI response lifecycle ends."""

    def __init__(self, *, snapshot: BinaryIO, **kwargs: object) -> None:
        self.snapshot = snapshot
        super().__init__(**kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.snapshot.close()


__all__ = ["SnapshotStreamingResponse"]
