from __future__ import annotations

from datetime import UTC, datetime
import re
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.auth.models import AuthSession
from app.security.passwords import hash_password
from app.users.models import User, UserRole


class UserNotFoundError(LookupError):
    pass


class InvalidUsernameError(ValueError):
    pass


class LastAdminError(RuntimeError):
    pass


_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_ADMIN_LIFECYCLE_LOCK = 4_741_536_956_790_001


def normalize_username(username: str) -> str:
    normalized = username.strip().casefold()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise InvalidUsernameError(
            "Username must be 3-80 lowercase letters, digits, dots, underscores, or hyphens"
        )
    return normalized


def _now() -> datetime:
    return datetime.now(UTC)


class UserService:
    def create_user(
        self,
        session: Session,
        *,
        username: str,
        display_name: str,
        role: UserRole,
        initial_password: str,
        created_by_id: UUID | None = None,
        now: datetime | None = None,
    ) -> User:
        normalized_username = normalize_username(username)
        clean_display_name = display_name.strip()
        if not clean_display_name:
            raise ValueError("Display name is required")
        user = User(
            username=normalized_username,
            normalized_username=normalized_username,
            display_name=clean_display_name,
            role=role,
            is_enabled=True,
            password_hash=hash_password(initial_password),
            must_change_password=True,
            password_changed_at=None,
            created_by_id=created_by_id,
        )
        session.add(user)
        session.flush()
        return user

    def reset_password(
        self,
        session: Session,
        user_id: UUID,
        one_time_password: str,
        *,
        now: datetime | None = None,
    ) -> User:
        changed_at = now or _now()
        user = self._get_for_update(session, user_id)
        user.password_hash = hash_password(one_time_password)
        user.must_change_password = True
        user.password_changed_at = changed_at
        self.revoke_sessions(
            session,
            user_id,
            reason="password_reset",
            now=changed_at,
        )
        session.flush()
        return user

    def change_password(
        self,
        session: Session,
        user: User,
        new_password: str,
        *,
        now: datetime | None = None,
    ) -> User:
        changed_at = now or _now()
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.password_changed_at = changed_at
        self.revoke_sessions(
            session,
            user.id,
            reason="password_changed",
            now=changed_at,
        )
        session.flush()
        return user

    def set_enabled(
        self,
        session: Session,
        user_id: UUID,
        is_enabled: bool,
        *,
        now: datetime | None = None,
    ) -> User:
        changed_at = now or _now()
        user = self._get_for_update(session, user_id)
        if user.role is UserRole.ADMIN and user.is_enabled and not is_enabled:
            self._guard_last_active_admin(session)
        if user.is_enabled != is_enabled:
            user.is_enabled = is_enabled
            self.revoke_sessions(
                session,
                user.id,
                reason="user_enabled_state_changed",
                now=changed_at,
            )
        session.flush()
        return user

    def set_role(
        self,
        session: Session,
        user_id: UUID,
        role: UserRole,
        *,
        now: datetime | None = None,
    ) -> User:
        changed_at = now or _now()
        user = self._get_for_update(session, user_id)
        if user.role is UserRole.ADMIN and user.is_enabled and role is not UserRole.ADMIN:
            self._guard_last_active_admin(session)
        if user.role is not role:
            user.role = role
            self.revoke_sessions(
                session,
                user.id,
                reason="role_changed",
                now=changed_at,
            )
        session.flush()
        return user

    def revoke_sessions(
        self,
        session: Session,
        user_id: UUID,
        *,
        reason: str = "admin_revocation",
        now: datetime | None = None,
    ) -> int:
        revoked_at = now or _now()
        result = session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revocation_reason=reason)
        )
        return int(result.rowcount or 0)

    def list_users(self, session: Session) -> list[User]:
        return list(session.scalars(select(User).order_by(User.username)))

    def _get_for_update(self, session: Session, user_id: UUID) -> User:
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise UserNotFoundError("User not found")
        return user

    def _guard_last_active_admin(self, session: Session) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": _ADMIN_LIFECYCLE_LOCK},
        )
        active_admins = session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.is_enabled.is_(True))
        )
        if int(active_admins or 0) <= 1:
            raise LastAdminError("The last enabled Admin cannot be disabled or demoted")

