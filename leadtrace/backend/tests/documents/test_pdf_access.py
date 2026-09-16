from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from starlette.requests import ClientDisconnect, Request

from app.assets.models import Asset, AssetIntegrityState
from app.assets.storage import LocalAssetStore
from app.audit.models import AuditEvent
from app.audit.service import AuditService
from app.security.policies import Principal
from app.users.models import UserRole
from app.workspaces.models import PaperWorkspace, ReviewTask, ReviewTaskState, WorkspaceState


def _login(client, username: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Document test password 2026!"},
    )
    assert response.status_code == 200


async def _disconnect_during_response_body(response) -> None:
    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("client disconnected")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "root_path": "",
    }
    await response(scope, receive, send)


def test_assigned_reviewer_and_admin_read_v2_source_pdf(document_fixture) -> None:
    for username in ("document.reviewer", "document.admin"):
        _login(document_fixture.client, username)
        response = document_fixture.client.get(f"/api/v2/papers/{document_fixture.paper_id}/source-pdf", headers={"X-Request-ID": f"source-{username}"})
        assert response.status_code == 200
        assert response.content == document_fixture.payload
        assert response.headers["Content-Type"] == "application/pdf"
        assert response.headers["Content-Length"] == str(len(document_fixture.payload))
        assert response.headers["Accept-Ranges"] == "bytes"
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert str(document_fixture.source_path) not in response.text
    with document_fixture.session_factory() as session:
        events = list(session.scalars(select(AuditEvent).where(AuditEvent.paper_id == document_fixture.paper_id).order_by(AuditEvent.occurred_at)))
        assert len(events) == 2
        assert all(event.action == "document.pdf.viewed" for event in events)
        assert all(event.target_id == document_fixture.asset_id for event in events)
        assert str(document_fixture.source_path) not in str([event.details for event in events])


def test_assigned_reviewer_reads_source_pdf_after_approval(document_fixture) -> None:
    with document_fixture.session_factory.begin() as session:
        task = session.scalar(
            select(ReviewTask).where(ReviewTask.paper_id == document_fixture.paper_id)
        )
        assert task is not None
        workspace = session.scalar(
            select(PaperWorkspace).where(PaperWorkspace.review_task_id == task.id)
        )
        assert workspace is not None
        task.status = ReviewTaskState.APPROVED
        workspace.state = WorkspaceState.APPROVED

    _login(document_fixture.client, "document.reviewer")
    response = document_fixture.client.get(
        f"/api/v2/papers/{document_fixture.paper_id}/source-pdf"
    )

    assert response.status_code == 200
    assert response.content == document_fixture.payload


def test_other_roles_and_unknown_paper_receive_hidden_404(document_fixture) -> None:
    for username in ("document.other", "document.visitor"):
        _login(document_fixture.client, username)
        response = document_fixture.client.get(f"/api/v2/papers/{document_fixture.paper_id}/source-pdf")
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
        assert b"%PDF" not in response.content
    _login(document_fixture.client, "document.admin")
    assert document_fixture.client.get(f"/api/v2/papers/{uuid4()}/source-pdf").status_code == 404


def test_unassigned_reviewer_cannot_bypass_source_pdf_scope_via_asset_route(
    document_fixture,
) -> None:
    _login(document_fixture.client, "document.other")

    response = document_fixture.client.get(
        f"/api/v1/assets/{document_fixture.asset_id}/content"
    )

    assert response.status_code == 404
    assert response.content != document_fixture.payload


def test_integrity_mismatch_fails_closed_without_path_leakage(document_fixture) -> None:
    document_fixture.source_path.write_bytes(document_fixture.payload + b"tampered")
    _login(document_fixture.client, "document.admin")
    response = document_fixture.client.get(f"/api/v2/papers/{document_fixture.paper_id}/source-pdf")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert str(document_fixture.source_path) not in response.text
    with document_fixture.session_factory() as session:
        asset = session.get(Asset, document_fixture.asset_id)
        assert asset is not None and asset.integrity_state is AssetIntegrityState.CORRUPT


def test_source_pdf_streams_the_snapshot_that_passed_integrity_check(
    document_fixture,
    monkeypatch,
) -> None:
    replacement = document_fixture.source_path.with_name("replacement.pdf")
    replacement_payload = b"R" * len(document_fixture.payload)
    replacement.write_bytes(replacement_payload)
    real_open = Path.open
    replaced = False

    def replace_after_open(path: Path, *args, **kwargs):
        nonlocal replaced
        handle = real_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if path == document_fixture.source_path and not replaced and "r" in mode:
            replaced = True
            os.replace(replacement, document_fixture.source_path)
        return handle

    monkeypatch.setattr(Path, "open", replace_after_open)
    _login(document_fixture.client, "document.reviewer")
    response = document_fixture.client.get(
        f"/api/v2/papers/{document_fixture.paper_id}/source-pdf",
        headers={"Range": "bytes=9-48"},
    )

    assert replaced is True
    assert response.status_code == 206
    assert response.content == document_fixture.payload[9:49]
    assert response.content != replacement_payload[9:49]


def test_source_pdf_closes_verified_snapshot_when_audit_append_fails(
    document_fixture,
    monkeypatch,
) -> None:
    _login(document_fixture.client, "document.reviewer")
    snapshots = []
    real_open_snapshot = LocalAssetStore.open_snapshot

    def track_snapshot(store, *args, **kwargs):
        inspected, snapshot = real_open_snapshot(store, *args, **kwargs)
        snapshots.append(snapshot)
        return inspected, snapshot

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(LocalAssetStore, "open_snapshot", track_snapshot)
    monkeypatch.setattr(AuditService, "append_event", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        document_fixture.client.get(
            f"/api/v2/papers/{document_fixture.paper_id}/source-pdf"
        )

    assert len(snapshots) == 1
    assert snapshots[0].closed is True


def test_source_pdf_closes_verified_snapshot_on_client_disconnect(
    document_fixture,
    monkeypatch,
) -> None:
    snapshots = []
    real_open_snapshot = LocalAssetStore.open_snapshot

    def track_snapshot(store, *args, **kwargs):
        inspected, snapshot = real_open_snapshot(store, *args, **kwargs)
        snapshots.append(snapshot)
        return inspected, snapshot

    monkeypatch.setattr(LocalAssetStore, "open_snapshot", track_snapshot)
    endpoint = next(
        route.endpoint
        for route in document_fixture.client.app.routes
        if getattr(route, "path", None) == "/api/v2/papers/{paper_id}/source-pdf"
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/v2/papers/{document_fixture.paper_id}/source-pdf",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "app": document_fixture.client.app,
        }
    )
    with document_fixture.session_factory() as session:
        response = endpoint(
            paper_id=document_fixture.paper_id,
            request=request,
            range_header=None,
            session=session,
            principal=Principal(
                user_id=document_fixture.reviewer_id,
                role=UserRole.REVIEWER,
            ),
        )

    async def assert_disconnect_closes_snapshot() -> None:
        with pytest.raises(ClientDisconnect):
            await _disconnect_during_response_body(response)
        assert snapshots[0].closed is True

    assert len(snapshots) == 1
    asyncio.run(assert_disconnect_closes_snapshot())
