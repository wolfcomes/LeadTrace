from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.assets.models import Asset, AssetIntegrityState
from app.audit.models import AuditEvent


def _login(client, username: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Document test password 2026!"},
    )
    assert response.status_code == 200


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


def test_other_roles_and_unknown_paper_receive_hidden_404(document_fixture) -> None:
    for username in ("document.other", "document.visitor"):
        _login(document_fixture.client, username)
        response = document_fixture.client.get(f"/api/v2/papers/{document_fixture.paper_id}/source-pdf")
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
        assert b"%PDF" not in response.content
    _login(document_fixture.client, "document.admin")
    assert document_fixture.client.get(f"/api/v2/papers/{uuid4()}/source-pdf").status_code == 404


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
