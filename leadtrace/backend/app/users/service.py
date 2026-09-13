from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.auth.models import AuthSession
from app.audit.service import AuditService, canonical_content_hash
from app.security.passwords import hash_password
from app.users.models import User, UserRole


class UserNotFoundError(LookupError):
    pass


class InvalidUsernameError(ValueError):
    pass


class LastAdminError(RuntimeError):
    pass


class AccountManagementForbidden(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class NonAdminPasswordResetResult:
    applied: bool
    role_counts: dict[UserRole, int]
    affected_user_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ManagedPasswordResetResult:
    user: User
    sessions_revoked: int


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


def _credential_audit_state(user: User) -> dict[str, object]:
    return {
        "user_id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "is_enabled": user.is_enabled,
        "must_change_password": user.must_change_password,
        "password_changed_at": (
            user.password_changed_at.isoformat()
            if user.password_changed_at is not None
            else None
        ),
    }


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
            must_change_password=False,
            password_changed_at=None,
            created_by_id=created_by_id,
        )
        session.add(user)
        session.flush()
        return user

    def create_managed_user(
        self,
        session: Session,
        *,
        actor_id: UUID,
        username: str,
        display_name: str,
        role: UserRole,
        default_password: str,
        request_id: str,
        ip_address: str = "local-cli",
        now: datetime | None = None,
    ) -> User:
        actor = self._require_enabled_admin(session, actor_id)
        created_at = now or _now()
        user = self.create_user(
            session,
            username=username,
            display_name=display_name,
            role=role,
            initial_password=default_password,
            created_by_id=actor.id,
            now=created_at,
        )
        self._append_account_audit(
            session,
            actor_id=actor.id,
            action="account.created",
            user=user,
            before={"exists": False},
            reason="Admin created a managed account",
            details={"role": user.role.value},
            request_id=request_id,
            ip_address=ip_address,
            occurred_at=created_at,
        )
        return user

    def bootstrap_admin(
        self,
        session: Session,
        *,
        username: str,
        display_name: str,
        default_password: str,
        request_id: str,
        ip_address: str = "local-cli",
        now: datetime | None = None,
    ) -> User:
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": _ADMIN_LIFECYCLE_LOCK},
        )
        if int(session.scalar(select(func.count()).select_from(User)) or 0) != 0:
            raise AccountManagementForbidden(
                "Admin bootstrap requires an empty user database"
            )
        created_at = now or _now()
        admin = self.create_user(
            session,
            username=username,
            display_name=display_name,
            role=UserRole.ADMIN,
            initial_password=default_password,
            now=created_at,
        )
        self._append_account_audit(
            session,
            actor_id=admin.id,
            action="account.bootstrap_created",
            user=admin,
            before={"exists": False},
            reason="Bootstrapped the first local Admin account",
            details={"bootstrap": True, "role": admin.role.value},
            request_id=request_id,
            ip_address=ip_address,
            occurred_at=created_at,
        )
        return admin

    def reset_password(
        self,
        session: Session,
        user_id: UUID,
        one_time_password: str,
        *,
        now: datetime | None = None,
    ) -> User:
        user = self._get_for_update(session, user_id)
        self._reset_locked_password(
            session,
            user,
            one_time_password,
            reason="password_reset",
            now=now,
        )
        return user

    def reset_managed_password(
        self,
        session: Session,
        *,
        actor_id: UUID,
        user_id: UUID,
        default_password: str,
        request_id: str,
        ip_address: str = "local-cli",
        now: datetime | None = None,
    ) -> ManagedPasswordResetResult:
        actor = self._require_enabled_admin(session, actor_id)
        user = self._get_for_update(session, user_id)
        before = _credential_audit_state(user)
        changed_at = now or _now()
        sessions_revoked = self._reset_locked_password(
            session,
            user,
            default_password,
            reason="managed_default_password_reset",
            now=changed_at,
        )
        self._append_account_audit(
            session,
            actor_id=actor.id,
            action="account.password_reset",
            user=user,
            before=before,
            reason="Admin reset a managed account to the configured default",
            details={
                "role": user.role.value,
                "sessions_revoked": sessions_revoked,
            },
            request_id=request_id,
            ip_address=ip_address,
            occurred_at=changed_at,
        )
        return ManagedPasswordResetResult(
            user=user,
            sessions_revoked=sessions_revoked,
        )

    def _reset_locked_password(
        self,
        session: Session,
        user: User,
        password: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> int:
        changed_at = now or _now()
        user.password_hash = hash_password(password)
        user.must_change_password = False
        user.password_changed_at = changed_at
        sessions_revoked = self.revoke_sessions(
            session,
            user.id,
            reason=reason,
            now=changed_at,
        )
        session.flush()
        return sessions_revoked

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

    def reset_non_admin_passwords_to_default(
        self,
        session: Session,
        *,
        actor_id: UUID,
        default_password: str,
        apply: bool,
        request_id: str,
        ip_address: str = "local-cli",
        now: datetime | None = None,
    ) -> NonAdminPasswordResetResult:
        actor = self._require_enabled_admin(session, actor_id)
        targets = list(
            session.scalars(
                select(User)
                .where(User.role.in_([UserRole.REVIEWER, UserRole.VISITOR]))
                .order_by(User.username)
                .with_for_update()
            )
        )
        role_counts = {
            UserRole.REVIEWER: sum(
                user.role is UserRole.REVIEWER for user in targets
            ),
            UserRole.VISITOR: sum(
                user.role is UserRole.VISITOR for user in targets
            ),
        }
        if not apply:
            return NonAdminPasswordResetResult(
                applied=False,
                role_counts=role_counts,
                affected_user_ids=(),
            )

        changed_at = now or _now()
        audit_service = AuditService()
        for user in targets:
            before = _credential_audit_state(user)
            user.password_hash = hash_password(default_password)
            user.must_change_password = False
            user.password_changed_at = changed_at
            revoked = self.revoke_sessions(
                session,
                user.id,
                reason="bulk_default_password_reset",
                now=changed_at,
            )
            after = _credential_audit_state(user)
            audit_service.append_event(
                session,
                actor_id=actor.id,
                action="account.bulk_default_reset",
                target_type="user",
                target_id=user.id,
                paper_id=None,
                changeset_id=None,
                release_id=None,
                ip_address=ip_address,
                request_id=request_id,
                result="success",
                reason="Admin reset a non-Admin account to the configured default",
                before_hash=canonical_content_hash(before),
                after_hash=canonical_content_hash(after),
                details={
                    "role": user.role.value,
                    "sessions_revoked": revoked,
                },
                occurred_at=changed_at,
            )
        session.flush()
        return NonAdminPasswordResetResult(
            applied=True,
            role_counts=role_counts,
            affected_user_ids=tuple(user.id for user in targets),
        )

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
        user = session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise UserNotFoundError("User not found")
        return user

    def _require_enabled_admin(self, session: Session, actor_id: UUID) -> User:
        try:
            actor = self._get_for_update(session, actor_id)
        except UserNotFoundError as error:
            raise AccountManagementForbidden(
                "An enabled Admin actor is required for account management"
            ) from error
        if not actor.is_enabled or actor.role is not UserRole.ADMIN:
            raise AccountManagementForbidden(
                "An enabled Admin actor is required for account management"
            )
        return actor

    @staticmethod
    def _append_account_audit(
        session: Session,
        *,
        actor_id: UUID,
        action: str,
        user: User,
        before: dict[str, object],
        reason: str,
        details: dict[str, object],
        request_id: str,
        ip_address: str,
        occurred_at: datetime,
    ) -> None:
        AuditService().append_event(
            session,
            actor_id=actor_id,
            action=action,
            target_type="user",
            target_id=user.id,
            paper_id=None,
            changeset_id=None,
            release_id=None,
            ip_address=ip_address,
            request_id=request_id,
            result="success",
            reason=reason,
            before_hash=canonical_content_hash(before),
            after_hash=canonical_content_hash(_credential_audit_state(user)),
            details=details,
            occurred_at=occurred_at,
        )

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
