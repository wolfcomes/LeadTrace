from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.auth.models import AuthSession
from app.maintenance.models import MaintenanceWindow
from app.security.sessions import SESSION_COOKIE_NAME, keyed_token_hash
from app.users.models import User, UserRole


class MaintenanceConflict(RuntimeError):
    pass


class MaintenanceModeActive(RuntimeError):
    pass


_MAINTENANCE_WRITE_FENCE = 4_741_536_956_790_023


@dataclass(frozen=True, slots=True)
class MaintenanceStatus:
    active: bool
    reason: str | None = None
    started_at: datetime | None = None
    expected_end_at: datetime | None = None
    started_by_id: UUID | None = None

    @classmethod
    def from_window(cls, window: MaintenanceWindow | None) -> "MaintenanceStatus":
        if window is None:
            return cls(active=False)
        return cls(
            active=True,
            reason=window.reason,
            started_at=window.started_at,
            expected_end_at=window.expected_end_at,
            started_by_id=window.started_by_id,
        )


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(UTC)


class MaintenanceService:
    def acquire_write_guard(self, session: Session) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock_shared(:lock_id)"),
            {"lock_id": _MAINTENANCE_WRITE_FENCE},
        )

    def _acquire_control_guard(self, session: Session) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": _MAINTENANCE_WRITE_FENCE},
        )

    def current(
        self,
        session: Session,
        *,
        for_update: bool = False,
    ) -> MaintenanceWindow | None:
        statement = select(MaintenanceWindow).where(
            MaintenanceWindow.active_slot == 1,
            MaintenanceWindow.ended_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    def status(self, session: Session) -> MaintenanceStatus:
        return MaintenanceStatus.from_window(self.current(session))

    def require_writes_enabled(self, session: Session) -> None:
        self.acquire_write_guard(session)
        window = self.current(session)
        if window is not None:
            raise MaintenanceModeActive("LeadTrace is temporarily read-only")

    def activate(
        self,
        session: Session,
        *,
        actor_id: UUID,
        reason: str,
        expected_end_at: datetime,
        now: datetime | None = None,
    ) -> MaintenanceWindow:
        self._acquire_control_guard(session)
        started_at = _aware_utc(now or datetime.now(UTC), "now")
        expected_end = _aware_utc(expected_end_at, "expected_end")
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValueError("Maintenance reason is required")
        if expected_end <= started_at:
            raise ValueError("Maintenance expected_end must be in the future")
        if self.current(session, for_update=True) is not None:
            raise MaintenanceConflict("Maintenance mode is already active")
        window = MaintenanceWindow(
            active_slot=1,
            reason=clean_reason,
            started_at=started_at,
            expected_end_at=expected_end,
            started_by_id=actor_id,
        )
        session.add(window)
        session.flush()
        return window

    def deactivate(
        self,
        session: Session,
        *,
        actor_id: UUID,
        reason: str,
        now: datetime | None = None,
    ) -> MaintenanceWindow:
        self._acquire_control_guard(session)
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValueError("Maintenance completion reason is required")
        window = self.current(session, for_update=True)
        if window is None:
            raise MaintenanceConflict("Maintenance mode is not active")
        ended_at = _aware_utc(now or datetime.now(UTC), "now")
        if ended_at < window.started_at:
            raise ValueError("Maintenance completion precedes its start")
        window.active_slot = None
        window.ended_at = ended_at
        window.ended_by_id = actor_id
        window.ended_reason = clean_reason
        session.flush()
        return window


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SAFE_WRITE_PREFIXES = ("/api/v1/auth/",)
_SAFE_WRITE_PATHS = frozenset({"/api/v1/admin/maintenance"})


def enforce_maintenance_mode(
    request: Request,
) -> Generator[None, None, None]:
    if request.method.upper() in _SAFE_METHODS:
        yield
        return
    if request.url.path.startswith(_SAFE_WRITE_PREFIXES):
        yield
        return
    if request.url.path in _SAFE_WRITE_PATHS:
        yield
        return
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        yield
        return
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        yield
        return
    guarded_user = False
    with factory() as session:
        checked_at = datetime.now(UTC)
        token_hash = keyed_token_hash(
            token,
            request.app.state.settings.session_secret.get_secret_value(),
            purpose="session",
        )
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash)
        )
        if auth_session is not None:
            user = session.get(User, auth_session.user_id)
            guarded_user = bool(
                auth_session.revoked_at is None
                and checked_at <= auth_session.idle_expires_at
                and checked_at <= auth_session.absolute_expires_at
                and user is not None
                and user.is_enabled
                and not user.must_change_password
                and user.role is not UserRole.VISITOR
            )
    if not guarded_user:
        yield
        return
    with factory.begin() as session:
        service = MaintenanceService()
        service.acquire_write_guard(session)
        status = MaintenanceService().status(session)
        if status.active:
            assert status.started_at is not None
            assert status.expected_end_at is not None
            raise APIError(
                503,
                "MAINTENANCE_MODE",
                "LeadTrace is temporarily read-only",
                details={
                    "reason": status.reason,
                    "started_at": status.started_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "expected_end": status.expected_end_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                },
            )
        yield


__all__ = [
    "MaintenanceConflict",
    "MaintenanceModeActive",
    "MaintenanceService",
    "MaintenanceStatus",
    "enforce_maintenance_mode",
]
