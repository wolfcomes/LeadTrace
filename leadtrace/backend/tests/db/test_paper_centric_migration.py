from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import DBAPIError

from app.auth.service import AuthService
from app.audit.service import AuditService
from app.database import create_database_engine, create_session_factory
from app.security.passwords import hash_password
from app.security.sessions import keyed_token_hash


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"

PAPER_CENTRIC_TABLES = {
    "paper_sources",
    "papers",
    "review_tasks",
    "paper_workspaces",
    "paper_section_reviews",
    "change_events",
}
PRESERVED_TABLES = {
    "users",
    "auth_sessions",
    "login_attempts",
    "assets",
    "audit_events",
    "audit_chain_head",
    "asset_scan_checkpoints",
    "crop_jobs",
    "crop_job_attempts",
    "crop_job_retry_operations",
    "maintenance_windows",
}
RETIRED_TABLES = {
    "activity_records",
    "approval_decisions",
    "changeset_items",
    "changeset_submissions",
    "changesets",
    "compounds",
    "crop_job_subscriptions",
    "evidence_records",
    "import_asset_links",
    "import_batches",
    "import_candidate_decisions",
    "import_release_candidates",
    "import_staging_records",
    "lineage_edges",
    "lineages",
    "molecule_proposals",
    "object_revisions",
    "paper_review_attestations",
    "paper_review_scopes",
    "release_artifact_manifests",
    "release_items",
    "release_operations",
    "releases",
    "review_comment_events",
    "review_comments",
    "revisioned_objects",
    "structures",
    "visual_object_asset_bindings",
    "visual_object_compound_bindings",
    "visual_object_region_bindings",
    "visual_object_relations",
    "visual_objects",
    "visual_regions",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        database_url
    ).database
    return config


def _public_tables(database_url: str) -> set[str]:
    engine = create_database_engine(database_url)
    try:
        return set(inspect(engine).get_table_names(schema="public"))
    finally:
        engine.dispose()


def _database_revision(database_url: str) -> str | None:
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def test_paper_centric_foundation_is_installed(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)

    command.upgrade(config, "0019_paper_centric_foundation")

    assert _database_revision(empty_postgresql_database_url) == (
        "0019_paper_centric_foundation"
    )
    tables = _public_tables(empty_postgresql_database_url)
    assert PAPER_CENTRIC_TABLES <= tables
    assert PRESERVED_TABLES <= tables
    assert RETIRED_TABLES.isdisjoint(tables)


def test_existing_admin_and_session_survive_paper_centric_transition(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "0017_unique_active_review_task")

    now = datetime.now(UTC).replace(microsecond=0)
    admin_id = uuid4()
    session_id = uuid4()
    asset_id = uuid4()
    crop_job_id = uuid4()
    maintenance_id = uuid4()
    password_hash = hash_password("Preserved Admin Password 2026!")
    session_secret = "task-1-preserved-session-secret-2026"
    session_token = "task-1-preserved-admin-session-token"
    session_token_hash = keyed_token_hash(
        session_token,
        session_secret,
        purpose="session",
    )
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, username, normalized_username, display_name, role,
                        is_enabled, password_hash, must_change_password,
                        password_changed_at, last_login_at, created_by_id,
                        created_at, updated_at
                    ) VALUES (
                        :id, 'preserved.admin', 'preserved.admin',
                        'Preserved Admin', 'admin', true, :password_hash, false,
                        :now, :now, NULL, :now, :now
                    )
                    """
                ),
                {"id": admin_id, "password_hash": password_hash, "now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO auth_sessions (
                        id, user_id, token_hash, csrf_hash, created_at,
                        last_seen_at, reauthenticated_at, idle_expires_at,
                        absolute_expires_at, revoked_at, revocation_reason
                    ) VALUES (
                        :id, :user_id, :token_hash, :csrf_hash, :now, :now,
                        :now, :idle_expires_at, :absolute_expires_at, NULL, NULL
                    )
                    """
                ),
                {
                    "id": session_id,
                    "user_id": admin_id,
                    "token_hash": session_token_hash,
                    "csrf_hash": "b" * 64,
                    "now": now,
                    "idle_expires_at": now + timedelta(hours=8),
                    "absolute_expires_at": now + timedelta(days=1),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO assets (
                        id, storage_key, original_filename, sha256, byte_size,
                        mime_type, category, access_level, integrity_state,
                        derivation_metadata, source_metadata, created_at,
                        updated_at
                    ) VALUES (
                        :id, 'source/source_pdfs/preserved.pdf',
                        'preserved.pdf', :sha256, 100, 'application/pdf',
                        'article_pdf', 'reviewer', 'verified', '{}'::jsonb,
                        '{}'::jsonb, :now, :now
                    )
                    """
                ),
                {"id": asset_id, "sha256": "e" * 64, "now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO crop_jobs (
                        id, input_hash, source_pdf_sha256, page_number,
                        x0, y0, x1, y1, rotation, padding, dpi,
                        renderer_version, status, created_by_id,
                        created_at, updated_at
                    ) VALUES (
                        :id, :input_hash, :source_hash, 1,
                        0.1, 0.1, 0.9, 0.9, 0, 0, 300,
                        'task1-test', 'pending', :admin_id, :now, :now
                    )
                    """
                ),
                {
                    "id": crop_job_id,
                    "input_hash": "c" * 64,
                    "source_hash": "d" * 64,
                    "admin_id": admin_id,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO maintenance_windows (
                        id, active_slot, reason, started_at, expected_end_at,
                        started_by_id
                    ) VALUES (
                        :id, 1, 'Task 1 preservation test', :now,
                        :expected_end_at, :admin_id
                    )
                    """
                ),
                {
                    "id": maintenance_id,
                    "now": now,
                    "expected_end_at": now + timedelta(hours=1),
                    "admin_id": admin_id,
                },
            )

        with create_session_factory(engine).begin() as session:
            audit_event = AuditService().append_event(
                session,
                actor_id=admin_id,
                action="paper_centric.transition_fixture",
                target_type="system",
                target_id=admin_id,
                paper_id=None,
                changeset_id=None,
                release_id=None,
                ip_address="127.0.0.1",
                request_id="task-1-preservation-test",
                result="success",
                reason="Prove audit history survives the transition",
                before_hash="0" * 64,
                after_hash="1" * 64,
                details={"fixture": "paper-centric-transition"},
                occurred_at=now,
            )
            audit_event_id = audit_event.id

        with engine.connect() as connection:
            audit_event_snapshot = connection.scalar(
                text(
                    "SELECT to_jsonb(audit_events) FROM audit_events "
                    "WHERE id = :event_id"
                ),
                {"event_id": audit_event_id},
            )
            audit_head_snapshot = connection.scalar(
                text("SELECT to_jsonb(audit_chain_head) FROM audit_chain_head")
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.connect() as connection:
            preserved_admin = connection.execute(
                text(
                    """
                    SELECT password_hash, is_enabled, role
                    FROM users
                    WHERE id = :admin_id
                    """
                ),
                {"admin_id": admin_id},
            ).one()
            preserved_session = connection.execute(
                text(
                    """
                    SELECT user_id, token_hash, revoked_at, absolute_expires_at
                    FROM auth_sessions
                    WHERE id = :session_id
                    """
                ),
                {"session_id": session_id},
            ).one()

            assert preserved_admin.password_hash == password_hash
            assert preserved_admin.is_enabled is True
            assert preserved_admin.role == "admin"
            assert preserved_session.user_id == admin_id
            assert preserved_session.token_hash == session_token_hash
            assert preserved_session.revoked_at is None
            assert preserved_session.absolute_expires_at > now
            assert connection.scalar(
                text("SELECT count(*) FROM assets WHERE id = :id"),
                {"id": asset_id},
            ) == 1
            assert connection.scalar(
                text("SELECT count(*) FROM crop_jobs WHERE id = :id"),
                {"id": crop_job_id},
            ) == 1
            assert connection.scalar(
                text("SELECT count(*) FROM maintenance_windows WHERE id = :id"),
                {"id": maintenance_id},
            ) == 1
            for table_name in PAPER_CENTRIC_TABLES:
                assert connection.scalar(
                    text(f'SELECT count(*) FROM "{table_name}"')
                ) == 0
            assert connection.scalar(
                text(
                    "SELECT to_jsonb(audit_events) FROM audit_events "
                    "WHERE id = :event_id"
                ),
                {"event_id": audit_event_id},
            ) == audit_event_snapshot
            assert connection.scalar(
                text("SELECT to_jsonb(audit_chain_head) FROM audit_chain_head")
            ) == audit_head_snapshot

        with create_session_factory(engine).begin() as session:
            authenticated = AuthService(session_secret).authenticate(
                session,
                session_token,
                now=now + timedelta(minutes=1),
            )
            assert authenticated.user.id == admin_id
            assert authenticated.user.role == "admin"
            audit_verification = AuditService().verify_chain(session)
            assert audit_verification.valid is True
            assert audit_verification.event_count == 1
    finally:
        engine.dispose()


def test_paper_centric_schema_enforces_the_fixed_workflow_contract(
    empty_postgresql_database_url: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        schema = inspect(engine)
        paper_columns = {
            column["name"] for column in schema.get_columns("papers")
        }
        assert paper_columns == {
            "abstract", "abstract_source", "pdb_references",
            "id",
            "paper_key",
            "source_id",
            "title",
            "journal",
            "publication_year",
            "volume",
            "issue",
            "doi",
            "catalog_state",
            "current_published_version_id",
            "created_at",
            "updated_at",
        }
        assert {
            (tuple(item["constrained_columns"]), item["referred_table"])
            for item in schema.get_foreign_keys("papers")
        } == {
            (("source_id",), "paper_sources"),
            (
                ("current_published_version_id", "id"),
                "published_paper_versions",
            ),
        }
        paper_source_checks = {
            item["name"] for item in schema.get_check_constraints("paper_sources")
        }
        assert {
            "ck_paper_sources_root_key_logical",
            "ck_paper_sources_source_key_relative_posix",
        } <= paper_source_checks

        expected_check_values = {
            "review_tasks": {
                "assigned",
                "submitted",
                "changes_requested",
                "approved",
            },
            "paper_workspaces": {"editing", "submitted", "approved"},
            "paper_section_reviews": {
                "bibliography",
                "compounds",
                "structures",
                "lineages",
                "edge_evidence",
                "activities",
                "pending",
                "completed",
                "not_reported",
            },
            "change_events": {"reviewer", "admin", "ai", "system"},
        }
        for table_name, values in expected_check_values.items():
            checks = " ".join(
                str(item["sqltext"])
                for item in schema.get_check_constraints(table_name)
            )
            assert all(value in checks for value in values)

        asset_foreign_keys = {
            tuple(item["constrained_columns"])
            for item in schema.get_foreign_keys("assets")
        }
        assert ("import_batch_id",) not in asset_foreign_keys
        audit_foreign_keys = {
            (tuple(item["constrained_columns"]), item["referred_table"])
            for item in schema.get_foreign_keys("audit_events")
        }
        assert (("paper_id",), "papers") in audit_foreign_keys
        assert all(
            columns not in {("changeset_id",), ("release_id",)}
            for columns, _ in audit_foreign_keys
        )
    finally:
        engine.dispose()


def _insert_paper_source(
    connection: Connection,
    *,
    source_root_key: str,
    source_key: str,
) -> UUID:
    now = datetime.now(UTC).replace(microsecond=0)
    asset_id = uuid4()
    source_id = uuid4()
    sha256 = uuid4().hex + uuid4().hex
    connection.execute(
        text(
            """
            INSERT INTO assets (
                id, storage_key, original_filename, sha256, byte_size,
                mime_type, category, access_level, integrity_state,
                derivation_metadata, source_metadata, created_at, updated_at
            ) VALUES (
                :id, :storage_key, 'article.pdf', :sha256, 100,
                'application/pdf', 'article_pdf', 'reviewer', 'verified',
                '{}'::jsonb, '{}'::jsonb, :now, :now
            )
            """
        ),
        {
            "id": asset_id,
            "storage_key": f"source/source_pdfs/{asset_id}.pdf",
            "sha256": sha256,
            "now": now,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO paper_sources (
                id, asset_id, source_root_key, source_key, sha256,
                byte_size, page_count, integrity_state, created_at, updated_at
            ) VALUES (
                :id, :asset_id, :source_root_key, :source_key, :sha256,
                100, 1, 'verified', :now, :now
            )
            """
        ),
        {
            "id": source_id,
            "asset_id": asset_id,
            "source_root_key": source_root_key,
            "source_key": source_key,
            "sha256": sha256,
            "now": now,
        },
    )
    return source_id


@pytest.mark.parametrize(
    "source_root_key",
    [
        "/data/source_pdfs",
        "../source_pdfs",
        "source/roots",
        "source\\roots",
        ".",
        "..",
        "C:\\source_pdfs",
    ],
)
def test_paper_sources_reject_physical_or_unsafe_root_keys(
    empty_postgresql_database_url: str,
    source_root_key: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with pytest.raises(DBAPIError) as error:
            with engine.begin() as connection:
                _insert_paper_source(
                    connection,
                    source_root_key=source_root_key,
                    source_key="volume67 issue5/article.pdf",
                )
        assert error.value.orig.sqlstate == "23514"
        assert error.value.orig.diag.constraint_name == (
            "ck_paper_sources_root_key_logical"
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "source_key",
    [
        "/data/source.pdf",
        "../source.pdf",
        "volume/../../source.pdf",
        "volume\\source.pdf",
        "volume/./source.pdf",
        "volume//source.pdf",
    ],
)
def test_paper_sources_reject_non_relative_or_non_posix_source_keys(
    empty_postgresql_database_url: str,
    source_key: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with pytest.raises(DBAPIError) as error:
            with engine.begin() as connection:
                _insert_paper_source(
                    connection,
                    source_root_key="source_pdfs",
                    source_key=source_key,
                )
        assert error.value.orig.sqlstate == "23514"
        assert error.value.orig.diag.constraint_name == (
            "ck_paper_sources_source_key_relative_posix"
        )
    finally:
        engine.dispose()


def test_paper_sources_accept_logical_root_and_relative_posix_source_key(
    empty_postgresql_database_url: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.begin() as connection:
            source_id = _insert_paper_source(
                connection,
                source_root_key="source_pdfs",
                source_key="volume67 issue5/article.pdf",
            )
            assert connection.execute(
                text(
                    "SELECT source_root_key, source_key FROM paper_sources "
                    "WHERE id = :id"
                ),
                {"id": source_id},
            ).one() == (
                "source_pdfs",
                "volume67 issue5/article.pdf",
            )
    finally:
        engine.dispose()


def test_upgrade_refuses_a_legacy_paper(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "0018_reviewer_scientific_workspace")
    paper_id = uuid4()
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO revisioned_objects (id, object_kind)
                    VALUES (:id, 'paper')
                    """
                ),
                {"id": paper_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO papers (id, paper_key, doi)
                    VALUES (:id, 'legacy-paper', NULL)
                    """
                ),
                {"id": paper_id},
            )
    finally:
        engine.dispose()

    with pytest.raises(DBAPIError, match="papers contains business rows"):
        command.upgrade(config, "head")

    assert _database_revision(empty_postgresql_database_url) == (
        "0018_reviewer_scientific_workspace"
    )
    assert "legacy-paper" in {
        row[0]
        for row in _query_all(
            empty_postgresql_database_url,
            "SELECT paper_key FROM papers",
        )
    }


def test_upgrade_refuses_a_legacy_crop_job_subscription(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "0018_reviewer_scientific_workspace")
    now = datetime.now(UTC).replace(microsecond=0)
    admin_id = uuid4()
    paper_id = uuid4()
    region_id = uuid4()
    job_id = uuid4()
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, username, normalized_username, display_name, role,
                        is_enabled, password_hash, must_change_password,
                        created_at, updated_at
                    ) VALUES (
                        :id, 'subscription.admin', 'subscription.admin',
                        'Subscription Admin', 'admin', true, :password_hash,
                        false, :now, :now
                    )
                    """
                ),
                {
                    "id": admin_id,
                    "password_hash": hash_password("Subscription Test 2026!"),
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO revisioned_objects (id, object_kind)
                    VALUES (:paper_id, 'paper'), (:region_id, 'visual_region')
                    """
                ),
                {"paper_id": paper_id, "region_id": region_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO papers (id, paper_key, doi)
                    VALUES (:id, 'subscription-paper', NULL)
                    """
                ),
                {"id": paper_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO visual_regions (
                        id, paper_id, region_key, page_number
                    ) VALUES (:id, :paper_id, 'region-1', 1)
                    """
                ),
                {"id": region_id, "paper_id": paper_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO crop_jobs (
                        id, input_hash, source_pdf_sha256, page_number,
                        x0, y0, x1, y1, rotation, padding, dpi,
                        renderer_version, status, created_by_id,
                        created_at, updated_at
                    ) VALUES (
                        :id, :input_hash, :source_hash, 1,
                        0.1, 0.1, 0.9, 0.9, 0, 0, 300,
                        'task1-test', 'pending', :admin_id, :now, :now
                    )
                    """
                ),
                {
                    "id": job_id,
                    "input_hash": "e" * 64,
                    "source_hash": "f" * 64,
                    "admin_id": admin_id,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO crop_job_subscriptions (
                        id, job_id, paper_id, region_id, requested_by_id
                    ) VALUES (
                        :id, :job_id, :paper_id, :region_id, :admin_id
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "job_id": job_id,
                    "paper_id": paper_id,
                    "region_id": region_id,
                    "admin_id": admin_id,
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(
        DBAPIError,
        match="crop_job_subscriptions contains business rows",
    ):
        command.upgrade(config, "head")

    assert _database_revision(empty_postgresql_database_url) == (
        "0018_reviewer_scientific_workspace"
    )


def _query_all(database_url: str, statement: str) -> list[tuple[object, ...]]:
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            return list(connection.execute(text(statement)).tuples())
    finally:
        engine.dispose()


def _install_change_event_fixture(database_url: str) -> tuple[object, object]:
    now = datetime.now(UTC).replace(microsecond=0)
    admin_id = uuid4()
    reviewer_id = uuid4()
    asset_id = uuid4()
    source_id = uuid4()
    paper_id = uuid4()
    task_id = uuid4()
    workspace_id = uuid4()
    event_id = uuid4()
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, username, normalized_username, display_name, role,
                        is_enabled, password_hash, must_change_password,
                        created_at, updated_at
                    ) VALUES
                        (:admin_id, 'event.admin', 'event.admin', 'Event Admin',
                         'admin', true, :password_hash, false, :now, :now),
                        (:reviewer_id, 'event.reviewer', 'event.reviewer',
                         'Event Reviewer', 'reviewer', true, :password_hash,
                         false, :now, :now)
                    """
                ),
                {
                    "admin_id": admin_id,
                    "reviewer_id": reviewer_id,
                    "password_hash": hash_password("Event Test 2026!"),
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO assets (
                        id, storage_key, original_filename, sha256, byte_size,
                        mime_type, category, access_level, integrity_state,
                        derivation_metadata, source_metadata, created_at,
                        updated_at
                    ) VALUES (
                        :id, 'source/source_pdfs/event.pdf', 'event.pdf',
                        :sha256, 100, 'application/pdf', 'article_pdf',
                        'reviewer', 'verified', '{}'::jsonb, '{}'::jsonb,
                        :now, :now
                    )
                    """
                ),
                {"id": asset_id, "sha256": "1" * 64, "now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO paper_sources (
                        id, asset_id, source_root_key, source_key, sha256,
                        byte_size, page_count, integrity_state,
                        created_at, updated_at
                    ) VALUES (
                        :id, :asset_id, 'source_pdfs', 'event.pdf', :sha256,
                        100, 1, 'verified', :now, :now
                    )
                    """
                ),
                {
                    "id": source_id,
                    "asset_id": asset_id,
                    "sha256": "1" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO papers (
                        id, paper_key, source_id, title, journal,
                        publication_year, volume, issue, catalog_state,
                        created_at, updated_at
                    ) VALUES (
                        :id, 'LT-TEST-001', :source_id, 'Test paper',
                        'Test journal', 2026, '1', '1', 'extracted', :now, :now
                    )
                    """
                ),
                {"id": paper_id, "source_id": source_id, "now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO review_tasks (
                        id, paper_id, assigned_reviewer_id, created_by_id,
                        status, version, created_at, updated_at
                    ) VALUES (
                        :id, :paper_id, :reviewer_id, :admin_id, 'assigned',
                        1, :now, :now
                    )
                    """
                ),
                {
                    "id": task_id,
                    "paper_id": paper_id,
                    "reviewer_id": reviewer_id,
                    "admin_id": admin_id,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO paper_workspaces (
                        id, paper_id, review_task_id, state, version,
                        created_at, updated_at
                    ) VALUES (
                        :id, :paper_id, :task_id, 'editing', 1, :now, :now
                    )
                    """
                ),
                {
                    "id": workspace_id,
                    "paper_id": paper_id,
                    "task_id": task_id,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO change_events (
                        id, paper_id, workspace_id, entity_type, entity_id,
                        action, before_value, after_value, actor_kind,
                        actor_id, ai_run_id, occurred_at
                    ) VALUES (
                        :id, :paper_id, :workspace_id, 'paper', :paper_id,
                        'create', NULL, '{"title": "Test paper"}'::jsonb,
                        'system', NULL, NULL, :now
                    )
                    """
                ),
                {
                    "id": event_id,
                    "paper_id": paper_id,
                    "workspace_id": workspace_id,
                    "now": now,
                },
            )
    finally:
        engine.dispose()
    return event_id, workspace_id


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE change_events SET action = 'rewrite' WHERE id = :event_id",
        "DELETE FROM change_events WHERE id = :event_id",
    ],
)
def test_change_events_are_database_append_only(
    empty_postgresql_database_url: str,
    statement: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    event_id, _ = _install_change_event_fixture(empty_postgresql_database_url)
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with pytest.raises(DBAPIError) as error:
            with engine.begin() as connection:
                connection.execute(text(statement), {"event_id": event_id})
        assert error.value.orig.sqlstate == "55000"
    finally:
        engine.dispose()


def test_change_event_actor_ownership_is_checked_by_postgresql(
    empty_postgresql_database_url: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    _, workspace_id = _install_change_event_fixture(empty_postgresql_database_url)
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with pytest.raises(DBAPIError) as error:
            with engine.begin() as connection:
                paper_id = connection.scalar(
                    text(
                        "SELECT paper_id FROM paper_workspaces WHERE id = :id"
                    ),
                    {"id": workspace_id},
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO change_events (
                            id, paper_id, workspace_id, entity_type, entity_id,
                            action, after_value, actor_kind, actor_id, occurred_at
                        ) VALUES (
                            :id, :paper_id, :workspace_id, 'paper', :paper_id,
                            'update', '{}'::jsonb, 'reviewer', NULL, now()
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "paper_id": paper_id,
                        "workspace_id": workspace_id,
                    },
                )
        assert error.value.orig.sqlstate == "23514"
    finally:
        engine.dispose()


def test_paper_centric_foundation_requires_restore_for_rollback(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")

    with pytest.raises(RuntimeError, match="restore.*backup"):
        command.downgrade(config, "0018_reviewer_scientific_workspace")

    assert _database_revision(empty_postgresql_database_url) == (
        "0019_paper_centric_foundation"
    )
