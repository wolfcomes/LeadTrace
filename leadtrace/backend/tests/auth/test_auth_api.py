from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import select

from app.auth.models import AuthSession
from app.audit.models import AuditEvent
from app.auth.router import resolve_remote_address
from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.users.models import User, UserRole
from app.users.service import UserService


PASSWORD = "Initial reviewer password 2026!"
MANAGED_DEFAULT_PASSWORD = "managed-default-test-password"


def _settings(tmp_path: Path, database_url: str, *, https_enabled: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="api-session-test-secret-more-than-thirty-two-characters",
        default_account_password=MANAGED_DEFAULT_PASSWORD,
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
        https_enabled=https_enabled,
    )


def test_client_address_ignores_forwarding_headers_from_untrusted_peer(
    tmp_path: Path,
) -> None:
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [
                (b"x-real-ip", b"203.0.113.99"),
                (b"x-forwarded-for", b"198.51.100.50"),
            ],
            "client": ("10.0.0.20", 50000),
        }
    )
    settings = _settings(
        tmp_path,
        "postgresql+psycopg://leadtrace:test@database/leadtrace_test",
    )

    assert resolve_remote_address(request, settings) == "10.0.0.20"


def test_client_address_accepts_valid_real_ip_from_explicit_trusted_proxy(
    tmp_path: Path,
) -> None:
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [(b"x-real-ip", b"203.0.113.99")],
            "client": ("172.30.97.10", 50000),
        }
    )
    settings = _settings(
        tmp_path,
        "postgresql+psycopg://leadtrace:test@database/leadtrace_test",
    )
    settings.trusted_proxy_addresses = ["172.30.97.10"]

    assert resolve_remote_address(request, settings) == "203.0.113.99"


@pytest.fixture
def api_client(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> TestClient:
    settings = _settings(tmp_path, empty_postgresql_database_url)
    with auth_session_factory.begin() as session:
        UserService().create_user(
            session,
            username="reviewer.one",
            display_name="Reviewer One",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
    engine = auth_session_factory.kw["bind"]
    resources = DatabaseResources(engine=engine, session_factory=auth_session_factory)
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        yield client


def test_login_sets_server_session_cookie_without_requiring_password_change(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer.one", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["user"] == {
        "username": "reviewer.one",
        "display_name": "Reviewer One",
        "role": "reviewer",
        "must_change_password": False,
    }
    assert response.json()["csrf_token"]
    cookie = response.headers["set-cookie"].lower()
    assert "leadtrace_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie


def test_login_error_does_not_reveal_username_or_disabled_state(
    api_client: TestClient,
) -> None:
    missing = api_client.post(
        "/api/v1/auth/login",
        json={"username": "does.not.exist", "password": PASSWORD},
    )
    wrong = api_client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer.one", "password": "wrong password"},
    )

    assert missing.status_code == wrong.status_code == 401
    for response in (missing, wrong):
        assert response.json() == {
            "code": "AUTHENTICATION_REQUIRED",
            "message": "Invalid username or password",
            "details": {},
            "request_id": response.headers["X-Request-ID"],
        }
    assert "does.not.exist" not in missing.text
    assert "reviewer.one" not in wrong.text


def test_authenticated_state_change_requires_csrf(api_client: TestClient) -> None:
    login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer.one", "password": PASSWORD},
    )

    missing_csrf = api_client.post("/api/v1/auth/logout")
    valid_csrf = api_client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )

    assert missing_csrf.status_code == 403
    assert valid_csrf.status_code == 204
    assert "max-age=0" in valid_csrf.headers["set-cookie"].lower()


def test_existing_cookie_restores_a_stable_multitab_csrf_token(
    api_client: TestClient,
) -> None:
    anonymous = api_client.get("/api/v1/auth/session")
    login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer.one", "password": PASSWORD},
    )

    restored_first_tab = api_client.get("/api/v1/auth/session")
    restored_second_tab = api_client.get("/api/v1/auth/session")
    assert anonymous.status_code == 401
    assert restored_first_tab.status_code == 200
    assert restored_second_tab.status_code == 200

    logout = api_client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": restored_first_tab.json()["csrf_token"]},
    )

    assert restored_first_tab.json()["user"] == login.json()["user"]
    assert (
        restored_first_tab.json()["csrf_token"]
        == restored_second_tab.json()["csrf_token"]
        == login.json()["csrf_token"]
    )
    assert "session" not in restored_first_tab.text.casefold()
    assert logout.status_code == 204


def test_password_change_rotates_session_and_clears_one_time_flag(
    api_client: TestClient,
) -> None:
    login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer.one", "password": PASSWORD},
    )
    old_cookie = api_client.cookies.get("leadtrace_session")

    changed = api_client.post(
        "/api/v1/auth/password",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
        json={
            "current_password": PASSWORD,
            "new_password": "Updated reviewer password 2026!",
        },
    )

    assert changed.status_code == 200
    assert changed.json()["user"]["must_change_password"] is False
    assert api_client.cookies.get("leadtrace_session") != old_cookie


def test_simple_six_character_password_can_be_set_and_used_for_login(
    api_client: TestClient,
) -> None:
    login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer.one", "password": PASSWORD},
    )

    changed = api_client.post(
        "/api/v1/auth/password",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
        json={"current_password": PASSWORD, "new_password": "simple"},
    )

    assert changed.status_code == 200
    logout = api_client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": changed.json()["csrf_token"]},
    )
    assert logout.status_code == 204

    relogin = api_client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer.one", "password": "simple"},
    )
    assert relogin.status_code == 200


def test_self_registration_route_does_not_exist(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/auth/register",
        json={"username": "new.user", "password": PASSWORD},
    )

    assert response.status_code == 404


def test_https_mode_marks_session_cookie_secure(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        UserService().create_user(
            session,
            username="visitor.one",
            display_name="Visitor One",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
    settings = _settings(tmp_path, empty_postgresql_database_url, https_enabled=True)
    engine = auth_session_factory.kw["bind"]
    resources = DatabaseResources(engine=engine, session_factory=auth_session_factory)
    app = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "visitor.one", "password": PASSWORD},
        )

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_legacy_password_flag_does_not_block_admin_role_permissions(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = True
        UserService().create_user(
            session,
            username="reviewer.one",
            display_name="Reviewer One",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
    settings = _settings(tmp_path, empty_postgresql_database_url)
    engine = auth_session_factory.kw["bind"]
    resources = DatabaseResources(engine=engine, session_factory=auth_session_factory)
    app = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )

    with TestClient(app) as client:
        admin_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin.one", "password": PASSWORD},
        )
        listed_with_legacy_flag = client.get("/api/v1/users")
        created_with_legacy_flag = client.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": admin_login.json()["csrf_token"]},
            json={
                "username": "visitor.blocked",
                "display_name": "Blocked Visitor",
                "role": "visitor",
            },
        )
        admin_password_change = client.post(
            "/api/v1/auth/password",
            headers={"X-CSRF-Token": admin_login.json()["csrf_token"]},
            json={
                "current_password": PASSWORD,
                "new_password": "Updated admin password 2026!",
            },
        )
        created = client.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": admin_password_change.json()["csrf_token"]},
            json={
                "username": "visitor.one",
                "display_name": "Visitor One",
                "role": "visitor",
            },
        )

        client.cookies.clear()
        managed_default_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "visitor.one",
                "password": MANAGED_DEFAULT_PASSWORD,
            },
        )
        client.cookies.clear()
        reviewer_login = client.post(
            "/api/v1/auth/login",
            json={"username": "reviewer.one", "password": PASSWORD},
        )
        reviewer_password_change = client.post(
            "/api/v1/auth/password",
            headers={"X-CSRF-Token": reviewer_login.json()["csrf_token"]},
            json={
                "current_password": PASSWORD,
                "new_password": "Updated reviewer password 2026!",
            },
        )
        forbidden = client.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": reviewer_password_change.json()["csrf_token"]},
            json={
                "username": "visitor.two",
                "display_name": "Visitor Two",
                "role": "visitor",
                "initial_password": "Initial visitor password 2026!",
            },
        )

    assert listed_with_legacy_flag.status_code == 200
    assert created_with_legacy_flag.status_code == 201
    assert admin_password_change.status_code == 200
    assert created.status_code == 201
    assert managed_default_login.status_code == 200
    assert created.json()["username"] == "visitor.one"
    assert "password_hash" not in created.text
    assert "initial_password" not in created.text
    assert PASSWORD not in created.text
    assert forbidden.status_code == 403
    with auth_session_factory.begin() as session:
        create_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "account.created",
                AuditEvent.target_id == UUID(created.json()["id"]),
            )
        )
    assert create_event is not None
    assert "password" not in str(create_event.details).casefold()


def test_admin_reset_uses_server_default_and_revokes_existing_session(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        target = UserService().create_user(
            session,
            username="visitor.one",
            display_name="Visitor One",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
    settings = _settings(tmp_path, empty_postgresql_database_url)
    engine = auth_session_factory.kw["bind"]
    resources = DatabaseResources(engine=engine, session_factory=auth_session_factory)
    app = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )

    with TestClient(app) as client:
        visitor_login = client.post(
            "/api/v1/auth/login",
            json={"username": target.username, "password": PASSWORD},
        )
        old_cookie = client.cookies.get("leadtrace_session")
        assert visitor_login.status_code == 200
        assert old_cookie is not None

        client.cookies.clear()
        admin_login = client.post(
            "/api/v1/auth/login",
            json={"username": admin.username, "password": PASSWORD},
        )
        reset = client.patch(
            f"/api/v1/users/{target.id}/password",
            headers={"X-CSRF-Token": admin_login.json()["csrf_token"]},
        )
        assert reset.status_code == 200

        client.cookies.clear()
        client.cookies.set("leadtrace_session", old_cookie)
        assert client.get("/api/v1/auth/session").status_code == 401

        client.cookies.clear()
        default_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": target.username,
                "password": MANAGED_DEFAULT_PASSWORD,
            },
        )

    assert default_login.status_code == 200
    with auth_session_factory.begin() as session:
        reset_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "account.password_reset",
                AuditEvent.target_id == target.id,
            )
        )
    assert reset_event is not None
    assert "password" not in str(reset_event.details).casefold()


def test_account_creation_fails_safely_when_server_default_is_missing(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        target = UserService().create_user(
            session,
            username="reviewer.existing",
            display_name="Existing Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        target_hash = target.password_hash
        target_changed_at = target.password_changed_at
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="api-session-test-secret-more-than-thirty-two-characters",
        default_account_password=None,
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    engine = auth_session_factory.kw["bind"]
    resources = DatabaseResources(engine=engine, session_factory=auth_session_factory)
    app = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )

    with TestClient(app) as client:
        target_login = client.post(
            "/api/v1/auth/login",
            json={"username": target.username, "password": PASSWORD},
        )
        assert target_login.status_code == 200
        client.cookies.clear()
        login = client.post(
            "/api/v1/auth/login",
            json={"username": admin.username, "password": PASSWORD},
        )
        response = client.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
            json={
                "username": "visitor.one",
                "display_name": "Visitor One",
                "role": "visitor",
            },
        )
        reset = client.patch(
            f"/api/v1/users/{target.id}/password",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )
        client.cookies.clear()
        old_password_login = client.post(
            "/api/v1/auth/login",
            json={"username": target.username, "password": PASSWORD},
        )

    assert response.status_code == 503
    assert response.json()["message"] == "Managed account provisioning is unavailable"
    assert reset.status_code == 503
    assert reset.json()["message"] == "Managed account provisioning is unavailable"
    assert old_password_login.status_code == 200
    with auth_session_factory.begin() as session:
        persisted_target = session.get(User, target.id)
        inserted = session.scalar(
            select(User).where(User.username == "visitor.one")
        )
        active_target_sessions = list(
            session.scalars(
                select(AuthSession).where(
                    AuthSession.user_id == target.id,
                    AuthSession.revoked_at.is_(None),
                )
            )
        )
    assert persisted_target is not None
    assert persisted_target.password_hash == target_hash
    assert persisted_target.password_changed_at == target_changed_at
    assert inserted is None
    assert len(active_target_sessions) == 2


def test_critical_admin_action_requires_recent_password_reauthentication(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        UserService().create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
    settings = _settings(tmp_path, empty_postgresql_database_url)
    engine = auth_session_factory.kw["bind"]
    resources = DatabaseResources(engine=engine, session_factory=auth_session_factory)
    app = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin.one", "password": PASSWORD},
        )
        password_change = client.post(
            "/api/v1/auth/password",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
            json={
                "current_password": PASSWORD,
                "new_password": "Updated admin password 2026!",
            },
        )
        with auth_session_factory.begin() as session:
            active = session.scalar(
                select(AuthSession).where(AuthSession.revoked_at.is_(None))
            )
            assert active is not None
            active.reauthenticated_at = datetime.now(UTC) - timedelta(hours=1)

        blocked = client.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": password_change.json()["csrf_token"]},
            json={
                "username": "visitor.blocked",
                "display_name": "Blocked Visitor",
                "role": "visitor",
            },
        )
        reauthenticated = client.post(
            "/api/v1/auth/reauthenticate",
            headers={"X-CSRF-Token": password_change.json()["csrf_token"]},
            json={"password": "Updated admin password 2026!"},
        )
        created = client.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": password_change.json()["csrf_token"]},
            json={
                "username": "visitor.one",
                "display_name": "Visitor One",
                "role": "visitor",
            },
        )

    assert blocked.status_code == 403
    assert blocked.json() == {
        "code": "RECENT_REAUTHENTICATION_REQUIRED",
        "message": "Recent reauthentication required",
        "details": {},
        "request_id": blocked.headers["X-Request-ID"],
    }
    assert reauthenticated.status_code == 204
    assert created.status_code == 201
