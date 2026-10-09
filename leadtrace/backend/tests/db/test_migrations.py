from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.database import (
    DatabaseResources,
    SchemaVersionError,
    create_database_engine,
    create_session_factory,
    validate_schema_version,
)
from app.main import create_app
from app.security.passwords import hash_password
from app.security.sessions import keyed_token_hash


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        database_url
    ).database
    return config


def _database_revision(database_url: str) -> str | None:
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def test_empty_database_is_rejected_until_migrated(
    empty_postgresql_database_url: str,
) -> None:
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with pytest.raises(SchemaVersionError, match="Alembic head"):
            validate_schema_version(engine, ALEMBIC_CONFIG_PATH)
    finally:
        engine.dispose()


def test_empty_postgresql_database_upgrades_to_single_alembic_head(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)

    command.upgrade(config, "head")

    script_head = ScriptDirectory.from_config(config).get_current_head()
    assert script_head is not None
    assert _database_revision(empty_postgresql_database_url) == script_head

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        assert inspect(engine).has_table("alembic_version")
        validate_schema_version(engine, ALEMBIC_CONFIG_PATH)
    finally:
        engine.dispose()


def test_preview_receipt_revision_adds_identity_and_idempotency_contract(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        schema = inspect(engine)
        marker_columns = {
            column["name"] for column in schema.get_columns("preview_markers")
        }
        assert marker_columns >= {
            "id",
            "instance_id",
            "baseline_sha256",
            "schema_revision",
            "created_at",
        }
        receipt_columns = {
            column["name"]
            for column in schema.get_columns("preview_application_receipts")
        }
        assert receipt_columns >= {
            "id",
            "instance_id",
            "application_id",
            "idempotency_key",
            "request_digest",
            "candidate_sha256",
            "payload_sha256",
            "source_sha256",
            "entity_map",
            "initial_snapshot",
            "committed_at",
        }
        unique_constraints = {
            tuple(item["column_names"])
            for item in schema.get_unique_constraints("preview_application_receipts")
        }
        assert ("instance_id", "idempotency_key") in unique_constraints
    finally:
        engine.dispose()


def test_legacy_admin_review_workflow_revision_contract(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == "0033_admin_ai_tasks"
    reviewer_revision = script.get_revision("0018_reviewer_scientific_workspace")
    assert reviewer_revision is not None
    assert reviewer_revision.down_revision == "0017_unique_active_review_task"
    command.upgrade(config, "0018_reviewer_scientific_workspace")

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        schema = inspect(engine)
        columns = {
            column["name"]: column
            for column in schema.get_columns("import_candidate_decisions")
        }
        assert set(columns) == {
            "id",
            "candidate_id",
            "decision",
            "actor_id",
            "reason",
            "manifest",
            "manifest_hash",
            "created_at",
        }
        foreign_keys = {
            (tuple(item["constrained_columns"]), item["referred_table"])
            for item in schema.get_foreign_keys("import_candidate_decisions")
        }
        assert foreign_keys >= {
            (("candidate_id",), "import_release_candidates"),
            (("actor_id",), "users"),
        }
        unique_constraints = {
            tuple(item["column_names"])
            for item in schema.get_unique_constraints("import_candidate_decisions")
        }
        assert ("candidate_id",) in unique_constraints
        check_sql = " ".join(
            str(item["sqltext"])
            for item in schema.get_check_constraints("import_candidate_decisions")
        )
        assert "approve" in check_sql and "reject" in check_sql
        assert "manifest_hash" in check_sql and "64" in check_sql

        release_operation_columns = {
            column["name"]: column
            for column in schema.get_columns("release_operations")
        }
        assert release_operation_columns["replaced_release_id"]["nullable"] is True
        release_operation_checks = " ".join(
            str(item["sqltext"])
            for item in schema.get_check_constraints("release_operations")
        )
        assert "baseline_publish" in release_operation_checks
        assert "machine_evidence" in release_operation_checks

        audit_columns = {
            column["name"]: column
            for column in schema.get_columns("audit_events")
        }
        assert audit_columns["paper_id"]["nullable"] is True
        review_indexes = {
            item["name"]: item for item in schema.get_indexes("review_tasks")
        }
        active_task_index = review_indexes["uq_review_tasks_active_paper"]
        assert active_task_index["unique"] is True
        assert active_task_index["column_names"] == ["paper_id"]
        predicate = str(
            active_task_index.get("dialect_options", {}).get(
                "postgresql_where", ""
            )
        )
        assert "completed" in predicate
    finally:
        engine.dispose()


def test_legacy_reviewer_scientific_workspace_revision_contract(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "0018_reviewer_scientific_workspace")

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        schema = inspect(engine)
        proposal_columns = {
            column["name"]: column
            for column in schema.get_columns("molecule_proposals")
        }
        assert proposal_columns.keys() >= {
            "id",
            "paper_id",
            "visual_object_id",
            "proposal_key",
            "model_run_key",
            "crop_asset_id",
            "source_region_id",
        }
        proposal_uniques = {
            tuple(item["column_names"])
            for item in schema.get_unique_constraints("molecule_proposals")
        }
        assert (
            "paper_id",
            "visual_object_id",
            "proposal_key",
            "model_run_key",
        ) in proposal_uniques

        scope_columns = {
            column["name"]: column
            for column in schema.get_columns("paper_review_scopes")
        }
        assert scope_columns.keys() >= {
            "id",
            "changeset_id",
            "paper_id",
            "base_release_id",
            "base_paper_revision_id",
            "snapshot",
            "scope_hash",
            "item_count",
            "created_by_id",
            "created_at",
        }
        scope_uniques = {
            tuple(item["column_names"])
            for item in schema.get_unique_constraints("paper_review_scopes")
        }
        assert ("changeset_id",) in scope_uniques

        attestation_columns = {
            column["name"]: column
            for column in schema.get_columns("paper_review_attestations")
        }
        assert attestation_columns.keys() >= {
            "id",
            "changeset_id",
            "scope_id",
            "paper_id",
            "paper_revision_id",
            "changeset_version",
            "scope_hash",
            "reviewer_id",
            "item_count",
            "resolved_count",
            "blocker_count",
            "statement",
            "created_at",
        }

        revision_columns = {
            column["name"]: column
            for column in schema.get_columns("object_revisions")
        }
        assert revision_columns["proposal_disposition"]["nullable"] is True
        revision_checks = " ".join(
            str(item["sqltext"])
            for item in schema.get_check_constraints("object_revisions")
        )
        for disposition in (
            "pending",
            "accepted",
            "corrected",
            "rejected",
            "not_applicable",
        ):
            assert disposition in revision_checks
    finally:
        engine.dispose()


def test_reviewer_workspace_downgrade_rejects_machine_evidence_operation(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "0018_reviewer_scientific_workspace")
    engine = create_database_engine(empty_postgresql_database_url)
    actor_id = uuid4()
    release_id = uuid4()
    created_at = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, username, normalized_username, display_name, role,
                        is_enabled, password_hash, must_change_password,
                        password_changed_at, created_at, updated_at
                    ) VALUES (
                        :actor_id, 'workspace-admin', 'workspace-admin',
                        'Workspace Admin', 'admin', true, :password_hash, false,
                        :created_at, :created_at, :created_at
                    )
                    """
                ),
                {
                    "actor_id": actor_id,
                    "password_hash": hash_password("Migration test password 2026!"),
                    "created_at": created_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO releases (
                        id, release_key, title, notes, metrics, published_by_id,
                        published_at, is_current, manifest_finalized
                    ) VALUES (
                        :release_id, 'machine-evidence-release',
                        'Machine evidence', '', '{}'::jsonb, :actor_id,
                        :created_at, true, true
                    )
                    """
                ),
                {
                    "actor_id": actor_id,
                    "release_id": release_id,
                    "created_at": created_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO release_operations (
                        id, operation_type, actor_id, idempotency_key,
                        request_hash, target_release_id, replaced_release_id,
                        result_release_id, reason, delta
                    ) VALUES (
                        :operation_id, 'machine_evidence', :actor_id,
                        'migration-machine-evidence', :request_hash, NULL, NULL,
                        :release_id, 'Downgrade guard', '{}'::jsonb
                    )
                    """
                ),
                {
                    "actor_id": actor_id,
                    "release_id": release_id,
                    "operation_id": uuid4(),
                    "request_hash": "f" * 64,
                },
            )

        with pytest.raises(RuntimeError, match="cannot be downgraded after use"):
            command.downgrade(config, "0017_unique_active_review_task")

        assert _database_revision(empty_postgresql_database_url) == (
            "0018_reviewer_scientific_workspace"
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "used_feature",
    ["candidate_decision", "baseline_publish", "corpus_audit"],
)
def test_initial_baseline_release_downgrade_rejects_used_features_before_ddl(
    empty_postgresql_database_url: str,
    used_feature: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "0016_initial_baseline_release")
    engine = create_database_engine(empty_postgresql_database_url)
    actor_id = uuid4()
    created_at = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
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
                        :id, :username, :username, 'Migration Admin', 'admin',
                        true, :password_hash, false, :created_at, NULL, NULL,
                        :created_at, :created_at
                    )
                    """
                ),
                {
                    "id": actor_id,
                    "username": f"migration-admin-{used_feature}",
                    "password_hash": hash_password("Migration test password 2026!"),
                    "created_at": created_at,
                },
            )
            if used_feature == "candidate_decision":
                batch_id = uuid4()
                candidate_id = uuid4()
                connection.execute(
                    text(
                        """
                        INSERT INTO import_batches (
                            id, source_fingerprint, status, counts, integrity,
                            asset_linkage, completed_at
                        ) VALUES (
                            :id, :fingerprint, 'completed', '{}'::jsonb,
                            '{}'::jsonb, '{}'::jsonb, :created_at
                        )
                        """
                    ),
                    {
                        "id": batch_id,
                        "fingerprint": "a" * 64,
                        "created_at": created_at,
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO import_release_candidates (
                            id, import_batch_id, status, manifest, is_current
                        ) VALUES (
                            :id, :batch_id, 'approved', '{}'::jsonb, false
                        )
                        """
                    ),
                    {"id": candidate_id, "batch_id": batch_id},
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO import_candidate_decisions (
                            id, candidate_id, decision, actor_id, reason,
                            manifest, manifest_hash
                        ) VALUES (
                            :id, :candidate_id, 'approve', :actor_id,
                            'Migration downgrade guard', '{}'::jsonb, :manifest_hash
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "candidate_id": candidate_id,
                        "actor_id": actor_id,
                        "manifest_hash": "b" * 64,
                    },
                )
            elif used_feature == "baseline_publish":
                release_id = uuid4()
                connection.execute(
                    text(
                        """
                        INSERT INTO releases (
                            id, release_key, title, notes, metrics,
                            published_by_id, published_at, is_current,
                            manifest_finalized
                        ) VALUES (
                            :id, :release_key, 'Migration Release', '',
                            '{}'::jsonb, :actor_id, :created_at, true, true
                        )
                        """
                    ),
                    {
                        "id": release_id,
                        "release_key": f"migration-{release_id}",
                        "actor_id": actor_id,
                        "created_at": created_at,
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO release_operations (
                            id, operation_type, actor_id, idempotency_key,
                            request_hash, target_release_id, replaced_release_id,
                            result_release_id, reason, delta
                        ) VALUES (
                            :id, 'baseline_publish', :actor_id, :key,
                            :request_hash, NULL, NULL, :release_id,
                            'Migration downgrade guard', '{}'::jsonb
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "actor_id": actor_id,
                        "key": f"migration-{uuid4()}",
                        "request_hash": "c" * 64,
                        "release_id": release_id,
                    },
                )
            else:
                connection.execute(
                    text(
                        """
                        INSERT INTO audit_events (
                            id, sequence_number, actor_id, action, target_type,
                            target_id, paper_id, changeset_id, release_id,
                            occurred_at, ip_address, request_id, result, reason,
                            before_hash, after_hash, details,
                            previous_event_hash, event_hash
                        ) VALUES (
                            :id, 1, :actor_id, 'baseline.approved',
                            'import_candidate', :target_id, NULL, NULL, NULL,
                            :created_at, '127.0.0.1', 'migration-guard',
                            'success', 'Migration downgrade guard',
                            :before_hash, :after_hash, '{}'::jsonb,
                            :previous_hash, :event_hash
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "actor_id": actor_id,
                        "target_id": uuid4(),
                        "created_at": created_at,
                        "before_hash": "0" * 64,
                        "after_hash": "d" * 64,
                        "previous_hash": "0" * 64,
                        "event_hash": "e" * 64,
                    },
                )

        with pytest.raises(RuntimeError, match="cannot be downgraded after use"):
            command.downgrade(config, "0015_crop_job_subscriptions")

        assert _database_revision(empty_postgresql_database_url) == (
            "0016_initial_baseline_release"
        )
        schema = inspect(engine)
        assert schema.has_table("import_candidate_decisions")
        release_operation_columns = {
            column["name"]: column
            for column in schema.get_columns("release_operations")
        }
        assert release_operation_columns["replaced_release_id"]["nullable"] is True
        release_operation_checks = " ".join(
            str(item["sqltext"])
            for item in schema.get_check_constraints("release_operations")
        )
        assert "baseline_publish" in release_operation_checks
        audit_columns = {
            column["name"]: column
            for column in schema.get_columns("audit_events")
        }
        assert audit_columns["paper_id"]["nullable"] is True
    finally:
        engine.dispose()


def test_paper_centric_foundation_requires_backup_restore_for_rollback(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")

    with pytest.raises(RuntimeError, match="restore.*backup"):
        command.downgrade(config, "0018_reviewer_scientific_workspace")

    assert _database_revision(empty_postgresql_database_url) == (
        "0019_paper_centric_foundation"
    )


@pytest.mark.parametrize(
    "url_prefix",
    ["postgresql+psycopg://", "postgresql://"],
)
def test_alembic_cli_uses_supported_runtime_database_urls(
    empty_postgresql_database_url: str,
    url_prefix: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    environment = os.environ.copy()
    environment["LEADTRACE_DATABASE_URL"] = empty_postgresql_database_url.replace(
        "postgresql+psycopg://",
        url_prefix,
        1,
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG_PATH),
            "current",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert expected_head in completed.stdout


def test_full_migration_chain_renders_as_offline_sql() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG_PATH),
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "CREATE TABLE ai_extraction_runs" in completed.stdout
    assert "offline migration requires an empty legacy releases table" in completed.stdout


def test_application_starts_only_after_empty_database_is_migrated(
    tmp_path: Path,
    empty_postgresql_database_url: str,
) -> None:
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="fresh-deployment-test-secret-over-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    application = create_app(settings=settings, database_probe=lambda _: True)

    with pytest.raises(SchemaVersionError):
        with TestClient(application):
            pass

    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")

    with TestClient(application) as client:
        assert client.get("/health/live").status_code == 200


def test_alembic_metadata_matches_the_migrated_schema(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")
    environment = os.environ.copy()
    environment["LEADTRACE_DATABASE_URL"] = empty_postgresql_database_url

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG_PATH),
            "check",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "No new upgrade operations detected" in completed.stdout


def test_existing_identity_schema_upgrades_through_security_hardening(
    tmp_path: Path,
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    script = ScriptDirectory.from_config(config)

    identity_hardening = script.get_revision("0002_identity_hardening")
    assert identity_hardening is not None
    assert identity_hardening.down_revision == "0001_identity"
    command.upgrade(config, "0001_identity")

    engine = create_database_engine(empty_postgresql_database_url)
    legacy_token = "legacy-session-token-that-must-be-revoked"
    session_secret = "migration-test-session-secret-over-thirty-two-characters"
    password = "Existing admin password 2026!"
    created_at = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    user_id = uuid4()
    session_id = uuid4()
    try:
        legacy_schema = inspect(engine)
        assert "reauthenticated_at" not in {
            column["name"] for column in legacy_schema.get_columns("auth_sessions")
        }
        assert "source_hash" not in {
            column["name"] for column in legacy_schema.get_columns("login_attempts")
        }
        with pytest.raises(SchemaVersionError, match="does not match Alembic head"):
            validate_schema_version(engine, ALEMBIC_CONFIG_PATH)

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
                        :id, 'admin.existing', 'admin.existing', 'Existing Admin',
                        'admin', true, :password_hash, false, :created_at, NULL,
                        NULL, :created_at, :created_at
                    )
                    """
                ),
                {
                    "id": user_id,
                    "password_hash": hash_password(password),
                    "created_at": created_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO auth_sessions (
                        id, user_id, token_hash, csrf_hash, created_at,
                        last_seen_at, idle_expires_at, absolute_expires_at,
                        revoked_at, revocation_reason
                    ) VALUES (
                        :id, :user_id, :token_hash, :csrf_hash, :created_at,
                        :created_at, :idle_expires_at, :absolute_expires_at,
                        NULL, NULL
                    )
                    """
                ),
                {
                    "id": session_id,
                    "user_id": user_id,
                    "token_hash": keyed_token_hash(
                        legacy_token,
                        session_secret,
                        purpose="session",
                    ),
                    "csrf_hash": "f" * 64,
                    "created_at": created_at,
                    "idle_expires_at": datetime(2026, 9, 10, 16, 0, tzinfo=UTC),
                    "absolute_expires_at": datetime(2026, 9, 11, 8, 0, tzinfo=UTC),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO login_attempts (
                        id, identity_hash, remote_address, was_successful,
                        attempted_at
                    ) VALUES (
                        :id, :identity_hash, '127.0.0.1', false, :attempted_at
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "identity_hash": "e" * 64,
                    "attempted_at": created_at,
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_database_engine(empty_postgresql_database_url)
    session_factory = create_session_factory(engine)
    try:
        hardened_schema = inspect(engine)
        session_columns = {
            column["name"]: column
            for column in hardened_schema.get_columns("auth_sessions")
        }
        attempt_columns = {
            column["name"]: column
            for column in hardened_schema.get_columns("login_attempts")
        }
        assert session_columns["reauthenticated_at"]["nullable"] is False
        assert attempt_columns["source_hash"]["nullable"] is False
        assert {
            index["name"] for index in hardened_schema.get_indexes("login_attempts")
        } >= {
            "ix_login_attempts_identity_time",
            "ix_login_attempts_source_time",
        }

        with engine.connect() as connection:
            migrated_session = connection.execute(
                text(
                    """
                    SELECT reauthenticated_at, revoked_at, revocation_reason
                    FROM auth_sessions
                    WHERE id = :id
                    """
                ),
                {"id": session_id},
            ).one()
            assert migrated_session.reauthenticated_at == created_at
            assert migrated_session.revoked_at is not None
            assert migrated_session.revocation_reason == "identity_hardening"
            assert connection.scalar(text("SELECT count(*) FROM login_attempts")) == 0

        resources = DatabaseResources(engine=engine, session_factory=session_factory)
        settings = Settings(
            _env_file=None,
            environment="test",
            database_url=empty_postgresql_database_url,
            redis_url="redis://127.0.0.1:6379/0",
            session_secret=session_secret,
            allowed_hosts=["testserver"],
            asset_root=tmp_path,
        )
        application = create_app(
            settings=settings,
            database_probe=lambda _: True,
            database_bootstrap=lambda _: resources,
        )
        with TestClient(application) as client:
            client.cookies.set("leadtrace_session", legacy_token)
            assert client.get("/api/v1/auth/session").status_code == 401
            client.cookies.clear()

            login = client.post(
                "/api/v1/auth/login",
                json={"username": "admin.existing", "password": password},
            )
            assert login.status_code == 200
            restored = client.get("/api/v1/auth/session")
            assert restored.status_code == 200
            assert restored.json()["csrf_token"] == login.json()["csrf_token"]

            rejected_csrf = client.post(
                "/api/v1/auth/reauthenticate",
                headers={"X-CSRF-Token": "invalid"},
                json={"password": password},
            )
            reauthenticated = client.post(
                "/api/v1/auth/reauthenticate",
                headers={"X-CSRF-Token": login.json()["csrf_token"]},
                json={"password": password},
            )
            assert rejected_csrf.status_code == 403
            assert reauthenticated.status_code == 204

            for attempt in range(5):
                failed = client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": f"unknown.user.{attempt}",
                        "password": "wrong password",
                    },
                )
                assert failed.status_code == 401
            throttled = client.post(
                "/api/v1/auth/login",
                json={"username": "admin.existing", "password": password},
            )
            assert throttled.status_code == 401
    finally:
        engine.dispose()


def test_explicit_test_migration_target_wins_over_ambient_runtime_url(
    monkeypatch: pytest.MonkeyPatch,
    empty_postgresql_database_url: str,
) -> None:
    missing_database_url = make_url(empty_postgresql_database_url).set(
        database="leadtrace_database_that_must_not_be_used"
    )
    monkeypatch.setenv(
        "LEADTRACE_DATABASE_URL",
        missing_database_url.render_as_string(hide_password=False),
    )
    config = _alembic_config(empty_postgresql_database_url)

    command.upgrade(config, "head")

    assert _database_revision(empty_postgresql_database_url) == (
        ScriptDirectory.from_config(config).get_current_head()
    )


def test_guarded_migration_rejects_a_different_connected_database(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    config.attributes["leadtrace_expected_database_name"] = "different_test"

    with pytest.raises(RuntimeError, match="expected database"):
        command.upgrade(config, "head")


def test_preview_revision_downgrades_to_existing_ai_schema_and_reupgrades(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "0025_ai_prefill_runs")
    command.upgrade(config, "0026_ai_prefill_preview_receipts")
    command.downgrade(config, "0025_ai_prefill_runs")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        schema = inspect(engine)
        assert schema.has_table("ai_extraction_runs")
        assert not schema.has_table("preview_markers")
        assert not schema.has_table("preview_application_receipts")
        assert _database_revision(empty_postgresql_database_url) == "0025_ai_prefill_runs"
        command.upgrade(config, "head")
        assert inspect(engine).has_table("preview_application_receipts")
        assert _database_revision(empty_postgresql_database_url) == ScriptDirectory.from_config(config).get_current_head()
    finally:
        engine.dispose()


def test_lineage_type_migration_defaults_checks_and_downgrades(empty_postgresql_database_url):
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "0026_ai_prefill_preview_receipts")
    command.upgrade(config, "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        schema = inspect(engine)
        column = next(item for item in schema.get_columns("lineages") if item["name"] == "lineage_type")
        assert column["nullable"] is False
        assert "unspecified" in column["default"]
        constraints = {item["name"]: item["sqltext"] for item in schema.get_check_constraints("lineages")}
        assert "synthesis" in constraints["ck_lineages_type"]
        command.downgrade(config, "0026_ai_prefill_preview_receipts")
        assert "lineage_type" not in {item["name"] for item in inspect(engine).get_columns("lineages")}
        command.upgrade(config, "head")
    finally:
        engine.dispose()
