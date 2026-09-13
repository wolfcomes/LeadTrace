from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.storage import LocalAssetStore
from app.audit.models import AuditEvent
from app.imports.models import (
    ImportAssetLink,
    ImportBatch,
    ImportReleaseCandidate,
    ImportStagingRecord,
)
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision
from app.security.policies import WorkflowState
from app.users.models import User
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


def test_admin_candidate_pdf_is_bound_to_the_selected_import_batch(
    document_fixture: DocumentFixture,
) -> None:
    newer_payload = b"%PDF-1.7\n% newer candidate\n%%EOF\n"
    inspected = LocalAssetStore(
        document_fixture.client.app.state.settings.asset_root
    ).put_bytes(newer_payload, suffix=".pdf")
    with document_fixture.session_factory.begin() as session:
        original_asset = session.get(Asset, document_fixture.article_asset_id)
        paper = session.get(Paper, document_fixture.paper_id)
        assert original_asset is not None and original_asset.import_batch_id is not None
        assert paper is not None
        original_asset.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        original_candidate = ImportReleaseCandidate(
            import_batch_id=original_asset.import_batch_id,
            status="imported_baseline",
            manifest={"counts": {"corpus_papers": 1}},
            is_current=False,
        )
        newer_batch = ImportBatch(
            source_fingerprint="f" * 64,
            status="completed",
            counts={"corpus_papers": 1},
            integrity={},
            asset_linkage={},
            completed_at=datetime.now(UTC),
        )
        session.add_all([original_candidate, newer_batch])
        session.flush()
        newer_candidate = ImportReleaseCandidate(
            import_batch_id=newer_batch.id,
            status="imported_baseline",
            manifest={"counts": {"corpus_papers": 1}},
            is_current=False,
        )
        newer_asset = Asset(
            storage_key=inspected.storage_key,
            original_filename="newer-candidate.pdf",
            sha256=inspected.sha256,
            byte_size=inspected.byte_size,
            mime_type="application/pdf",
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            import_batch_id=newer_batch.id,
            derivation_metadata={},
            source_metadata={},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.add_all([newer_candidate, newer_asset])
        session.flush()
        session.add_all(
            [
                ImportStagingRecord(
                    import_batch_id=original_asset.import_batch_id,
                    record_type="paper",
                    original_id=paper.paper_key,
                    source_file="source_pdfs/articles/article-document.pdf",
                    source_row_locator="1",
                    source_hash="c" * 64,
                    raw_values={},
                    normalized_values={"paper_id": paper.paper_key},
                ),
                ImportStagingRecord(
                    import_batch_id=newer_batch.id,
                    record_type="paper",
                    original_id=paper.paper_key,
                    source_file="source_pdfs/articles/newer-candidate.pdf",
                    source_row_locator="1",
                    source_hash="d" * 64,
                    raw_values={},
                    normalized_values={"paper_id": paper.paper_key},
                ),
                ImportAssetLink(
                import_batch_id=newer_batch.id,
                record_type="paper",
                original_id=paper.paper_key,
                asset_id=newer_asset.id,
                link_role="article_pdf",
                source_reference="source_pdfs/articles/newer-candidate.pdf",
                ),
            ]
        )
        admin = session.scalar(
            select(User).where(User.username == "document.admin")
        )
        assert admin is not None
        revision = ObjectRevision(
            object_id=paper.id,
            revision_number=1,
            predecessor_id=None,
            changeset_id=None,
            actor_id=admin.id,
            reason="Release-scoped document test",
            content_hash="e" * 64,
            search_text=paper.paper_key,
            snapshot={
                "record_type": "paper",
                "original_id": paper.paper_key,
                "normalized_values": {"paper_id": paper.paper_key},
            },
            workflow_state=WorkflowState.PUBLISHED,
            is_current_published=True,
            is_tombstone=False,
        )
        release = Release(
            release_key="document-original-release",
            title="Document original release",
            notes="",
            metrics={
                "baseline": {"batch_id": str(original_asset.import_batch_id)}
            },
            source_candidate_id=original_candidate.id,
            published_by_id=admin.id,
            published_at=datetime.now(UTC),
            is_current=False,
            manifest_finalized=False,
        )
        session.add_all([revision, release])
        session.flush()
        session.add(
            ReleaseItem(
                release_id=release.id,
                object_id=paper.id,
                revision_id=revision.id,
                paper_id=paper.id,
                object_kind=ObjectKind.PAPER,
                manifest_order=1,
            )
        )
        session.flush()
        release.manifest_finalized = True
        original_candidate_id = original_candidate.id
        newer_candidate_id = newer_candidate.id
        release_id = release.id

    login(document_fixture.client, "document.admin")
    original = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        params={"candidate_id": str(original_candidate_id)},
    )
    newer = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        params={"candidate_id": str(newer_candidate_id)},
    )
    frozen_release = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        params={"release_id": str(release_id)},
    )
    ambiguous = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        params={
            "candidate_id": str(original_candidate_id),
            "release_id": str(release_id),
        },
    )

    assert original.status_code == newer.status_code == frozen_release.status_code == 200
    assert ambiguous.status_code == 404
    assert original.content == document_fixture.article_payload
    assert newer.content == newer_payload
    assert frozen_release.content == document_fixture.article_payload

    login(document_fixture.client, "document.reviewer")
    concealed_candidate = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        params={"candidate_id": str(original_candidate_id)},
    )
    assigned_release = document_fixture.client.get(
        f"/api/v1/papers/{document_fixture.paper_id}/source-pdf",
        params={"release_id": str(release_id)},
    )

    assert concealed_candidate.status_code == 404
    assert assigned_release.status_code == 200
    assert assigned_release.content == document_fixture.article_payload


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
