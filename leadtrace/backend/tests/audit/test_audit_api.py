from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.audit.service import AuditService, canonical_content_hash
from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.papers.models import Paper
from app.releases.models import Release
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Audit API password 2026!"


def _login(client: TestClient, username: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200


def test_audit_api_limits_reviewer_to_own_activity_and_admin_verifies_chain(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        users = UserService()
        identities = {}
        for name, role in (
            ("audit-reviewer", UserRole.REVIEWER),
            ("audit-visitor", UserRole.VISITOR),
            ("audit-admin", UserRole.ADMIN),
        ):
            user = users.create_user(
                session,
                username=f"{name}-{uuid4().hex[:8]}",
                display_name=name,
                role=role,
                initial_password=PASSWORD,
            )
            user.must_change_password = False
            identities[name] = user
        paper = Paper(paper_key=f"audit-api-paper-{uuid4().hex[:8]}", doi=None)
        session.add(paper)
        session.flush()
        release = Release(
            release_key=f"audit-api-release-{uuid4().hex[:8]}",
            title="Audit API release",
            notes="",
            metrics={},
            published_by_id=identities["audit-admin"].id,
            published_at=datetime.now(UTC),
            is_current=False,
            manifest_finalized=True,
        )
        session.add(release)
        session.flush()
        for index, actor_name in enumerate(("audit-reviewer", "audit-admin"), 1):
            AuditService().append_event(
                session,
                actor_id=identities[actor_name].id,
                action="review.comment.created",
                target_type="review_comment",
                target_id=uuid4(),
                paper_id=paper.id,
                changeset_id=None,
                release_id=release.id,
                ip_address="192.0.2.20",
                request_id=f"audit-api-{index}",
                result="success",
                reason="API visibility test",
                before_hash=canonical_content_hash(None),
                after_hash=canonical_content_hash({"index": index}),
                details={"password": "must-not-appear", "safe": actor_name},
            )
        AuditService().append_event(
            session,
            actor_id=identities["audit-admin"].id,
            action="import_candidate.approved",
            target_type="import_release_candidate",
            target_id=uuid4(),
            paper_id=None,
            changeset_id=None,
            release_id=None,
            ip_address="192.0.2.20",
            request_id="audit-api-corpus",
            result="success",
            reason="Corpus-level baseline decision",
            before_hash=canonical_content_hash({"status": "imported_baseline"}),
            after_hash=canonical_content_hash({"status": "approved"}),
            details={"scope": "corpus"},
        )

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="audit-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        _login(client, identities["audit-visitor"].username)
        assert client.get("/api/v1/audit/events").status_code == 403

        _login(client, identities["audit-reviewer"].username)
        reviewer_events = client.get("/api/v1/audit/events")
        assert reviewer_events.status_code == 200
        assert [event["actor_id"] for event in reviewer_events.json()] == [
            str(identities["audit-reviewer"].id)
        ]
        assert reviewer_events.json()[0]["details"] == {
            "password": "[REDACTED]",
            "safe": "audit-reviewer",
        }
        assert client.get("/api/v1/audit/verify").status_code == 403

        _login(client, identities["audit-admin"].username)
        admin_events = client.get("/api/v1/audit/events")
        assert admin_events.status_code == 200
        assert len(admin_events.json()) == 3
        corpus_event = next(
            event
            for event in admin_events.json()
            if event["action"] == "import_candidate.approved"
        )
        assert corpus_event["paper_id"] is None
        verification = client.get("/api/v1/audit/verify")
        assert verification.status_code == 200
        assert verification.json() == {
            "valid": True,
            "event_count": 3,
            "first_invalid_sequence": None,
        }
