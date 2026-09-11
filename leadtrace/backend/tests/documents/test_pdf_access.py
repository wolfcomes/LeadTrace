from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.assets.models import Asset, AssetAccessLevel, AssetIntegrityState
from app.audit.models import AuditEvent
from tests.documents.conftest import DocumentFixture, login


def test_visitor_cannot_read_article_or_si_pdf_bytes(
    document_fixture: DocumentFixture,
) -> None:
    client = document_fixture.client
    login(client, "document.visitor")

    article = client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        headers={"X-Request-ID": "visitor-article-pdf"},
    )
    si = client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        params={"kind": "si"},
    )

    assert article.status_code == si.status_code == 403
    assert b"%PDF" not in article.content + si.content
    assert "/tmp/" not in article.text
    assert article.headers["X-Request-ID"] == "visitor-article-pdf"


def test_unassigned_reviewer_cannot_read_pdf_bytes(
    document_fixture: DocumentFixture,
) -> None:
    login(document_fixture.client, "document.other")

    response = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf"
    )

    assert response.status_code == 403
    assert b"%PDF" not in response.content


def test_assigned_reviewer_reads_article_pdf_with_safe_headers_and_audit(
    document_fixture: DocumentFixture,
) -> None:
    login(document_fixture.client, "document.reviewer")

    response = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        headers={"X-Request-ID": "assigned-reviewer-pdf"},
    )

    assert response.status_code == 200
    assert response.content == document_fixture.article_payload
    assert response.headers["Content-Type"] == "application/pdf"
    assert response.headers["Content-Length"] == str(len(document_fixture.article_payload))
    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["ETag"] == f'"{_asset_hash(document_fixture, article=True)}"'
    assert response.headers["Content-Disposition"] == 'inline; filename="article-document.pdf"'
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "/tmp/" not in response.text

    with document_fixture.session_factory() as session:
        event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.request_id == "assigned-reviewer-pdf")
        )
        assert event is not None
        assert event.action == "document.pdf.viewed"
        assert event.target_id == document_fixture.article_asset_id
        assert event.paper_id == document_fixture.paper_id
        assert event.details["asset_id"] == str(document_fixture.article_asset_id)
        assert "/tmp/" not in str(event.details)


def test_admin_reads_supporting_information_pdf(
    document_fixture: DocumentFixture,
) -> None:
    login(document_fixture.client, "document.admin")

    response = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        params={"kind": "si"},
    )

    assert response.status_code == 200
    assert response.content == document_fixture.si_payload
    assert response.headers["Content-Disposition"] == (
        'inline; filename="supporting-information.pdf"'
    )


def test_assigned_reviewer_cannot_read_admin_only_pdf(
    document_fixture: DocumentFixture,
) -> None:
    with document_fixture.session_factory.begin() as session:
        asset = session.get(Asset, document_fixture.article_asset_id)
        assert asset is not None
        asset.access_level = AssetAccessLevel.ADMIN

    login(document_fixture.client, "document.reviewer")
    response = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf"
    )

    assert response.status_code == 404
    assert b"%PDF" not in response.content


def test_managed_pdf_can_use_internal_nginx_transfer(
    document_fixture: DocumentFixture,
) -> None:
    document_fixture.client.app.state.settings.nginx_internal_transfer = True
    login(document_fixture.client, "document.admin")

    response = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf"
    )

    asset_hash = _asset_hash(document_fixture, article=True)
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["X-Accel-Redirect"] == (
        f"/_leadtrace_internal_assets/objects/{asset_hash[:2]}/{asset_hash}.pdf"
    )


def test_unknown_paper_and_unusable_asset_have_safe_not_found_responses(
    document_fixture: DocumentFixture,
) -> None:
    login(document_fixture.client, "document.admin")

    missing = document_fixture.client.get(f"/api/v1/papers/{uuid4()}/source-pdf")
    assert missing.status_code == 404
    assert missing.json()["code"] == "RESOURCE_NOT_FOUND"
    assert "/tmp/" not in missing.text

    with document_fixture.session_factory.begin() as session:
        asset = session.get(Asset, document_fixture.article_asset_id)
        assert asset is not None
        asset.integrity_state = AssetIntegrityState.CORRUPT

    corrupt = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf"
    )
    assert corrupt.status_code == 404
    assert corrupt.json()["code"] == "RESOURCE_NOT_FOUND"
    assert "/tmp/" not in corrupt.text


def _asset_hash(document_fixture: DocumentFixture, *, article: bool) -> str:
    asset_id = (
        document_fixture.article_asset_id
        if article
        else document_fixture.si_asset_id
    )
    with document_fixture.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        return asset.sha256


def test_nginx_document_transfer_location_is_internal() -> None:
    config = Path(__file__).resolve().parents[3] / "deploy" / "nginx" / "nginx.conf"
    content = config.read_text(encoding="utf-8")

    assert "location /_leadtrace_internal_assets/" in content
    assert "        internal;" in content
