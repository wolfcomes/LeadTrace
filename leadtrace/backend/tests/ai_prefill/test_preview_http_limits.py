"""ASGI stream tests avoid a client that combines chunks before delivery."""
import asyncio
import json

import pytest
from starlette.responses import Response
from fastapi.testclient import TestClient

from app.ai_prefill.preview_http_limits import (
    MAX_PREVIEW_REQUEST_BYTES,
    PreviewRequestBodyLimitMiddleware,
)
from app.config import Settings
from app.main import create_app


async def _request(chunks, *, headers=(), path="/api/v2/admin/ai-prefill/candidates", method="POST"):
    received = 0
    called = []
    sent = []
    events = iter([{"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
                   for i, chunk in enumerate(chunks)])
    async def receive():
        nonlocal received
        received += 1
        return next(events)
    async def send(message):
        sent.append(message)
    async def endpoint(scope, downstream_receive, downstream_send):
        content = bytearray()
        while True:
            message = await downstream_receive()
            content.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        called.append(bytes(content))
        await Response("accepted")(scope, downstream_receive, downstream_send)
    scope = {"type": "http", "method": method, "path": path, "headers": list(headers)}
    await PreviewRequestBodyLimitMiddleware(endpoint)(scope, receive, send)
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    content = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return status, content, received, called


@pytest.mark.parametrize("headers", [(), ((b"content-length", b"1"),),
                                     ((b"transfer-encoding", b"chunked"),),
                                     ((b"content-length", b"invalid"),)])
@pytest.mark.parametrize("suffix", ["candidates", "candidates/c1/validations", "candidates/c1/preview-applications"])
def test_stream_size_limit_stops_before_endpoint_or_remaining_chunks(headers, suffix):
    chunks = [b"a" * (MAX_PREVIEW_REQUEST_BYTES // 2), b"b" * (MAX_PREVIEW_REQUEST_BYTES // 2), b"c", b"never read"]
    status, content, received, called = asyncio.run(_request(chunks, headers=headers, path=f"/api/v2/admin/ai-prefill/{suffix}"))
    assert status == 413
    assert json.loads(content)["code"] == "PREVIEW_REQUEST_TOO_LARGE"
    assert received == 3
    assert called == []


def test_declared_oversize_rejects_without_reading_upload():
    status, _, received, called = asyncio.run(_request([b"never read"], headers=[(b"content-length", str(MAX_PREVIEW_REQUEST_BYTES + 1).encode())]))
    assert status == 413
    assert received == 0
    assert called == []


def test_exact_limit_replays_all_chunks_once():
    chunks = [b"a" * (MAX_PREVIEW_REQUEST_BYTES // 2), b"", b"b" * (MAX_PREVIEW_REQUEST_BYTES // 2)]
    status, _, received, called = asyncio.run(_request(chunks))
    assert status == 200
    assert received == len(chunks)
    assert called == [b"".join(chunks)]


@pytest.mark.parametrize("path", ["/api/v2/admin/papers/id/ai-prefill", "/api/v2/admin/ai-prefill-other"])
def test_legacy_and_neighboring_paths_are_not_limited(path):
    body = b"a" * (MAX_PREVIEW_REQUEST_BYTES + 1)
    status, _, _, called = asyncio.run(_request([body], path=path))
    assert status == 200
    assert called == [body]


def test_middleware_is_not_installed_in_production(tmp_path):
    settings = Settings(
        _env_file=None, environment="production",
        database_url="postgresql+psycopg://unreachable@127.0.0.1/unused",
        session_secret="c" * 64, metrics_bearer_token="d" * 64,
        default_account_password="Initial account password 2026!",
        allowed_hosts=["leadtrace.test"], asset_root=tmp_path,
    )
    with TestClient(create_app(settings=settings, database_bootstrap=lambda _: None), base_url="http://leadtrace.test") as client:
        response = client.post("/api/v2/admin/ai-prefill/candidates", content=b"a" * (MAX_PREVIEW_REQUEST_BYTES + 1))
    assert response.status_code == 404
