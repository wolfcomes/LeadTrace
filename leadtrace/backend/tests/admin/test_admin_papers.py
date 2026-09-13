from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from app.approvals.service import ApprovalService
from app.config import Settings
from app.database import DatabaseResources
from app.imports.models import ImportBatch, ImportReleaseCandidate, ImportStagingRecord
from app.main import create_app
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.reviews.service import ReviewService
from app.revisions.models import ObjectKind, ObjectRevision
from app.security.policies import WorkflowState
from app.users.models import User, UserRole
from app.users.service import UserService


PASSWORD = "Admin catalog test password 2026!"


def _client(
    tmp_path: Path,
    database_url: str,
    factory: sessionmaker[Session],
) -> TestClient:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="admin-paper-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "assets",
    )
    resources = DatabaseResources(
        engine=factory.kw["bind"],
        session_factory=factory,
    )
    return TestClient(
        create_app(
            settings=settings,
            database_probe=lambda _: True,
            database_bootstrap=lambda _: resources,
        )
    )


def _user(
    session: Session,
    *,
    username: str,
    role: UserRole,
) -> User:
    user = UserService().create_user(
        session,
        username=username,
        display_name=username.replace(".", " ").title(),
        role=role,
        initial_password=PASSWORD,
    )
    user.must_change_password = False
    return user


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _paper_revision(
    session: Session,
    *,
    paper: Paper,
    actor: User,
    title: str,
) -> ObjectRevision:
    revision = ObjectRevision(
        object_id=paper.id,
        revision_number=1,
        predecessor_id=None,
        changeset_id=None,
        actor_id=actor.id,
        reason="Authoritative baseline import",
        content_hash=uuid4().hex + uuid4().hex,
        search_text=title,
        snapshot={
            "record_type": "paper",
            "original_id": paper.paper_key,
            "normalized_values": {
                "paper_id": paper.paper_key,
                "title_guess": title,
                "filename_year": "2024",
            },
        },
        workflow_state=WorkflowState.PUBLISHED,
        is_current_published=True,
        is_tombstone=False,
    )
    session.add(revision)
    session.flush()
    return revision


def _seed_five_states(session: Session) -> dict[str, Paper]:
    admin = _user(session, username="admin.catalog", role=UserRole.ADMIN)
    reviewer = _user(session, username="reviewer.catalog", role=UserRole.REVIEWER)
    papers = {
        state: Paper(paper_key=f"paper-{index}", doi=f"10.1000/{index}")
        for index, state in enumerate(
            (
                "initial",
                "ai_baseline_unassigned",
                "ai_baseline_in_review",
                "human_review_pending_approval",
                "admin_approved",
            ),
            start=1,
        )
    }
    session.add_all(papers.values())
    session.flush()

    release = Release(
        release_key="baseline-catalog",
        title="AI 提取基线",
        notes="",
        metrics={
            "dataset": {
                "dataset_class": "ai_extracted_baseline",
                # AI baselines must stay visibly unverified even if stale
                # metadata contains a contradictory value.
                "verification_status": "human_verified",
            }
        },
        published_by_id=admin.id,
        published_at=datetime.now(UTC),
        is_current=True,
        manifest_finalized=False,
    )
    session.add(release)
    session.flush()

    for order, (state, paper) in enumerate(papers.items(), start=1):
        if state == "initial":
            continue
        revision = _paper_revision(
            session,
            paper=paper,
            actor=admin,
            title=f"{state} article",
        )
        session.add(
            ReleaseItem(
                release_id=release.id,
                object_id=paper.id,
                revision_id=revision.id,
                paper_id=paper.id,
                object_kind=ObjectKind.PAPER,
                manifest_order=order,
            )
        )

    session.flush()
    release.manifest_finalized = True
    session.flush()

    review = ReviewService()
    for state in (
        "ai_baseline_in_review",
        "human_review_pending_approval",
        "admin_approved",
    ):
        paper = papers[state]
        task = review.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
            priority=50,
        )
        if state == "ai_baseline_in_review":
            continue
        changeset = review.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title=f"Review {state}",
            reason="Catalog state test",
        )
        base_revision_id = session.scalar(
            select(ReleaseItem.revision_id).where(
                ReleaseItem.release_id == release.id,
                ReleaseItem.paper_id == paper.id,
                ReleaseItem.object_kind == ObjectKind.PAPER,
            )
        )
        assert base_revision_id is not None
        review.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
            object_id=paper.id,
            object_kind=ObjectKind.PAPER.value,
            base_revision_id=base_revision_id,
            proposed_snapshot={
                "record_type": "paper",
                "original_id": paper.paper_key,
                "normalized_values": {
                    "paper_id": paper.paper_key,
                    "title_guess": f"Reviewed {state} article",
                    "filename_year": "2024",
                },
            },
        )
        review.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
        )
        if state == "admin_approved":
            ApprovalService().approve(
                session,
                changeset_id=changeset.id,
                actor_id=admin.id,
                reason="Approved for catalog state test",
                expected_version=changeset.version,
            )
    session.flush()
    return papers


def test_admin_catalog_lists_and_filters_all_five_workflow_states(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        papers = _seed_five_states(session)
        batch = ImportBatch(
            source_fingerprint="9" * 64,
            status="completed",
            counts={"corpus_papers": 1},
            integrity={},
            asset_linkage={},
            completed_at=datetime.now(UTC),
        )
        session.add(batch)
        session.flush()
        candidate = ImportReleaseCandidate(
            import_batch_id=batch.id,
            status="imported_baseline",
            manifest={"counts": {"corpus_papers": 1}},
            is_current=False,
        )
        session.add(candidate)
        session.add(
            ImportStagingRecord(
                import_batch_id=batch.id,
                record_type="paper",
                original_id=papers["ai_baseline_in_review"].paper_key,
                source_file="candidate/paper.json",
                source_row_locator="1",
                source_hash="8" * 64,
                raw_values={},
                normalized_values={
                    "paper_id": papers["ai_baseline_in_review"].paper_key,
                    "title_guess": "New unpublished candidate article",
                },
            )
        )
        session.flush()
        candidate_id = candidate.id

    release_projection_statements: list[str] = []

    def capture_release_projection(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if "release_items" in statement and "object_revisions" in statement:
            release_projection_statements.append(statement)

    engine = auth_session_factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture_release_projection)
    with _client(
        tmp_path, empty_postgresql_database_url, auth_session_factory
    ) as client:
        _login(client, "admin.catalog")
        response = client.get("/api/v1/admin/papers?page=1&page_size=20")
        event.remove(engine, "before_cursor_execute", capture_release_projection)
        filtered = client.get(
            "/api/v1/admin/papers",
            params={"workflow_state": "human_review_pending_approval"},
        )
        candidate_response = client.get(
            "/api/v1/admin/papers",
            params={"candidate_id": str(candidate_id)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total_items"] == 5
    assert payload["status_counts"] == {
        "initial": 1,
        "ai_baseline_unassigned": 1,
        "ai_baseline_in_review": 1,
        "human_review_pending_approval": 1,
        "admin_approved": 1,
    }
    by_id = {item["id"]: item for item in payload["items"]}
    unassigned = by_id[str(papers["ai_baseline_unassigned"].id)]
    assert unassigned["publication_status"] == "published"
    assert unassigned["verification_status"] == "unverified"
    assert unassigned["title"] == "ai_baseline_unassigned article"
    assert by_id[str(papers["ai_baseline_in_review"].id)]["task"][
        "assignee_display_name"
    ] == "Reviewer Catalog"
    assert by_id[str(papers["admin_approved"].id)]["changeset"][
        "workflow_state"
    ] == "approved"
    assert len(release_projection_statements) >= 2
    assert all(
        "release_items.object_kind" in statement
        or "release_items.paper_id" in statement
        for statement in release_projection_statements
    )

    assert filtered.status_code == 200
    assert filtered.json()["pagination"]["total_items"] == 1
    assert filtered.json()["items"][0]["workflow_state"] == (
        "human_review_pending_approval"
    )
    candidate_item = candidate_response.json()["items"][0]
    assert candidate_response.json()["source"]["publication_status"] == "unpublished"
    assert candidate_item["publication_status"] == "unpublished"
    assert candidate_item["can_modify"] is False
    assert candidate_item["modification_blocker"] == "baseline_must_be_published"


def test_admin_catalog_isolates_an_unpublished_candidate_from_other_database_papers(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        _user(session, username="admin.catalog", role=UserRole.ADMIN)
        imported = Paper(paper_key="paper-imported", doi="10.1000/imported")
        initial = Paper(paper_key="paper-initial", doi=None)
        session.add_all([imported, initial])
        session.flush()
        batch = ImportBatch(
            source_fingerprint=uuid4().hex + uuid4().hex,
            status="completed",
            counts={"corpus_papers": 1},
            integrity={},
            asset_linkage={},
            completed_at=datetime.now(UTC),
        )
        session.add(batch)
        session.flush()
        candidate = ImportReleaseCandidate(
            import_batch_id=batch.id,
            status="imported_baseline",
            manifest={"revision_count": 1, "counts": {"corpus_papers": 1}},
            is_current=False,
        )
        session.add(candidate)
        session.add_all(
            [
                ImportStagingRecord(
                import_batch_id=batch.id,
                record_type="paper",
                original_id=imported.paper_key,
                source_file="/private/source/articles/imported.pdf",
                source_row_locator="1",
                source_hash=uuid4().hex + uuid4().hex,
                raw_values={"source_pdf": "/private/source/articles/imported.pdf"},
                normalized_values={
                    "paper_id": imported.paper_key,
                    "title_guess": "Imported candidate article",
                    "filename_year": "2023",
                },
                ),
                ImportStagingRecord(
                    import_batch_id=batch.id,
                    record_type="compound",
                    original_id="compound-imported-1",
                    source_file="/private/source/compound.csv",
                    source_row_locator="2",
                    source_hash=uuid4().hex + uuid4().hex,
                    raw_values={},
                    normalized_values={"paper_id": imported.paper_key},
                ),
            ]
        )
        session.flush()
        candidate_id = candidate.id

    staging_statements: list[str] = []

    def capture_staging_sql(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if "import_staging_records" in statement:
            staging_statements.append(statement)

    engine = auth_session_factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture_staging_sql)
    try:
        with _client(
            tmp_path, empty_postgresql_database_url, auth_session_factory
        ) as client:
            _login(client, "admin.catalog")
            response = client.get(
                "/api/v1/admin/papers",
                params={"candidate_id": str(candidate_id)},
            )
            event.remove(engine, "before_cursor_execute", capture_staging_sql)
            detail = client.get(f"/api/v1/admin/papers/{imported.id}")
            excluded_detail = client.get(
                f"/api/v1/admin/papers/{initial.id}",
                params={"candidate_id": str(candidate_id)},
            )
            with auth_session_factory.begin() as session:
                stored_candidate = session.get(ImportReleaseCandidate, candidate_id)
                assert stored_candidate is not None
                stored_candidate.manifest = {
                    **stored_candidate.manifest,
                    "counts": {"corpus_papers": 2},
                }
            inconsistent = client.get(
                "/api/v1/admin/papers",
                params={"candidate_id": str(candidate_id)},
            )
            with auth_session_factory.begin() as session:
                stored_candidate = session.get(ImportReleaseCandidate, candidate_id)
                stored_paper = session.get(Paper, imported.id)
                assert stored_candidate is not None and stored_paper is not None
                stored_candidate.manifest = {
                    **stored_candidate.manifest,
                    "counts": {"corpus_papers": 1},
                }
                session.delete(stored_paper)
            missing_database_paper = client.get(
                "/api/v1/admin/papers",
                params={"candidate_id": str(candidate_id)},
            )
    finally:
        if event.contains(engine, "before_cursor_execute", capture_staging_sql):
            event.remove(engine, "before_cursor_execute", capture_staging_sql)

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["kind"] == "candidate"
    assert payload["source"]["candidate_id"] == str(candidate_id)
    assert payload["source"]["publication_status"] == "unpublished"
    assert payload["source"]["verification_status"] == "unverified"
    assert payload["pagination"]["total_items"] == 1
    assert payload["status_counts"]["ai_baseline_unassigned"] == 1
    assert payload["status_counts"]["initial"] == 0
    assert payload["items"][0]["quality"]["compounds"] == 1
    assert len(staging_statements) >= 2
    assert all(
        "record_type" in statement or "normalized_values" in statement
        for statement in staging_statements
    )
    assert "private/source" not in response.text

    assert detail.status_code == 200
    assert detail.json()["paper"]["title"] == "Imported candidate article"
    assert detail.json()["paper"]["can_modify"] is False
    assert detail.json()["paper"]["modification_blocker"] == (
        "baseline_must_be_published"
    )
    assert detail.json()["source_pdf_url"].endswith(
        f"kind=article&candidate_id={candidate_id}"
    )
    assert "private/source" not in detail.text
    assert excluded_detail.status_code == 404
    assert inconsistent.status_code == 409
    assert missing_database_paper.status_code == 409


def test_admin_catalog_pairs_a_new_active_task_only_with_its_own_changeset(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        papers = _seed_five_states(session)
        admin = session.scalar(select(User).where(User.username == "admin.catalog"))
        reviewer = session.scalar(
            select(User).where(User.username == "reviewer.catalog")
        )
        assert admin is not None and reviewer is not None
        new_task = ReviewService().create_task(
            session,
            paper_id=papers["admin_approved"].id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
            priority=80,
        )
        new_task_id = new_task.id
        paper_id = papers["admin_approved"].id

    with _client(
        tmp_path, empty_postgresql_database_url, auth_session_factory
    ) as client:
        _login(client, "admin.catalog")
        detail = client.get(f"/api/v1/admin/papers/{paper_id}")

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["paper"]["workflow_state"] == "ai_baseline_in_review"
    assert payload["paper"]["task"]["id"] == str(new_task_id)
    assert payload["paper"]["changeset"] is None
    assert payload["review_entry"] == f"/review/changesets?task={new_task_id}"


def test_admin_catalog_is_forbidden_to_reviewer(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        _user(session, username="reviewer.catalog", role=UserRole.REVIEWER)

    with _client(
        tmp_path, empty_postgresql_database_url, auth_session_factory
    ) as client:
        _login(client, "reviewer.catalog")
        response = client.get("/api/v1/admin/papers")

    assert response.status_code == 403
