from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.users.models import UserRole


class Action(StrEnum):
    READ_PUBLISHED_DATA = "read_published_data"
    READ_APPROVED_EVIDENCE = "read_approved_evidence"
    READ_FULL_PDF = "read_full_pdf"
    READ_DRAFT = "read_draft"
    CREATE_DRAFT = "create_draft"
    EDIT_DRAFT = "edit_draft"
    SUBMIT_CHANGESET = "submit_changeset"
    APPROVE_CHANGESET = "approve_changeset"
    PUBLISH_RELEASE = "publish_release"
    ROLLBACK_RELEASE = "rollback_release"
    MANAGE_ACCOUNTS = "manage_accounts"
    EXPORT_UNPUBLISHED = "export_unpublished"
    READ_AUDIT = "read_audit"


class WorkflowState(StrEnum):
    DRAFT = "draft"
    REVISED_DRAFT = "revised_draft"
    SUBMITTED = "submitted"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    role: UserRole
    must_change_password: bool = False
    csrf_hash: str | None = field(default=None, repr=False, compare=False)
    reauthenticated_at: datetime | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ResourceScope:
    exists: bool = True
    is_published: bool = False
    is_approved: bool = False
    assigned_reviewer_ids: frozenset[UUID] = frozenset()
    owner_id: UUID | None = None
    workflow_state: WorkflowState | None = None


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    status_code: int
    reason: str


_CONCEALED_READ_ACTIONS = frozenset(
    {
        Action.READ_PUBLISHED_DATA,
        Action.READ_APPROVED_EVIDENCE,
        Action.READ_FULL_PDF,
        Action.READ_DRAFT,
        Action.READ_AUDIT,
    }
)
_CONCEALED_UNPUBLISHED_ACTIONS = frozenset(
    {
        Action.EDIT_DRAFT,
        Action.SUBMIT_CHANGESET,
        Action.EXPORT_UNPUBLISHED,
    }
)


def _allow() -> AccessDecision:
    return AccessDecision(True, 200, "Allowed")


def _deny(action: Action, resource: ResourceScope) -> AccessDecision:
    if (action in _CONCEALED_READ_ACTIONS and not resource.is_published) or (
        action in _CONCEALED_UNPUBLISHED_ACTIONS and not resource.is_published
    ):
        return AccessDecision(False, 404, "Resource not found")
    return AccessDecision(False, 403, "Permission denied")


def evaluate_access(
    principal: Principal | None,
    action: Action,
    resource: ResourceScope,
) -> AccessDecision:
    """Evaluate the approved role matrix with resource-level boundaries."""

    if principal is None:
        return AccessDecision(False, 401, "Authentication required")
    if principal.must_change_password:
        return AccessDecision(False, 403, "Password change required")
    if not resource.exists:
        return AccessDecision(False, 404, "Resource not found")

    allowed_states = {
        Action.EDIT_DRAFT: {WorkflowState.DRAFT, WorkflowState.REVISED_DRAFT},
        Action.SUBMIT_CHANGESET: {
            WorkflowState.DRAFT,
            WorkflowState.REVISED_DRAFT,
        },
        Action.APPROVE_CHANGESET: {WorkflowState.SUBMITTED},
        Action.PUBLISH_RELEASE: {WorkflowState.APPROVED},
        Action.ROLLBACK_RELEASE: {
            WorkflowState.PUBLISHED,
            WorkflowState.SUPERSEDED,
        },
    }
    if action in allowed_states and resource.workflow_state not in allowed_states[action]:
        return _deny(action, resource)
    if principal.role == UserRole.ADMIN:
        return _allow()

    if action == Action.READ_PUBLISHED_DATA:
        return _allow() if resource.is_published else _deny(action, resource)
    if action == Action.READ_APPROVED_EVIDENCE:
        return (
            _allow()
            if resource.is_published and resource.is_approved
            else _deny(action, resource)
        )
    if principal.role == UserRole.VISITOR:
        return _deny(action, resource)

    is_assigned = principal.user_id in resource.assigned_reviewer_ids
    is_owned = resource.owner_id == principal.user_id
    if action in {Action.READ_FULL_PDF, Action.CREATE_DRAFT} and is_assigned:
        return _allow()
    if action in {
        Action.READ_DRAFT,
        Action.EDIT_DRAFT,
        Action.SUBMIT_CHANGESET,
        Action.EXPORT_UNPUBLISHED,
    } and is_assigned and is_owned:
        return _allow()
    if action == Action.READ_AUDIT and is_owned:
        return _allow()
    return _deny(action, resource)
