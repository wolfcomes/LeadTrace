from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException

from app.security.permissions import enforce_permission
from app.security.policies import Action, Principal, ResourceScope
from app.users.models import UserRole


REVIEWER_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_REVIEWER_ID = UUID("20000000-0000-0000-0000-000000000002")
VISITOR_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_unassigned_unpublished_resource_is_concealed_as_not_found() -> None:
    principal = Principal(REVIEWER_ID, UserRole.REVIEWER)
    other_draft = ResourceScope(
        assigned_reviewer_ids=frozenset({OTHER_REVIEWER_ID}),
        owner_id=OTHER_REVIEWER_ID,
    )

    with pytest.raises(HTTPException) as denied:
        enforce_permission(principal, Action.READ_DRAFT, other_draft)

    assert denied.value.status_code == 404
    assert denied.value.detail == "Resource not found"


def test_missing_resource_is_not_distinguishable_from_hidden_resource() -> None:
    principal = Principal(REVIEWER_ID, UserRole.REVIEWER)

    with pytest.raises(HTTPException) as denied:
        enforce_permission(
            principal,
            Action.READ_DRAFT,
            ResourceScope(exists=False),
        )

    assert denied.value.status_code == 404
    assert denied.value.detail == "Resource not found"


def test_unpublished_id_is_hidden_from_visitor_published_reads() -> None:
    visitor = Principal(VISITOR_ID, UserRole.VISITOR)

    with pytest.raises(HTTPException) as denied:
        enforce_permission(
            visitor,
            Action.READ_PUBLISHED_DATA,
            ResourceScope(is_published=False),
        )

    assert denied.value.status_code == 404
    assert denied.value.detail == "Resource not found"


def test_known_disallowed_action_returns_forbidden() -> None:
    principal = Principal(REVIEWER_ID, UserRole.REVIEWER)

    with pytest.raises(HTTPException) as denied:
        enforce_permission(
            principal,
            Action.PUBLISH_RELEASE,
            ResourceScope(is_published=True),
        )

    assert denied.value.status_code == 403
    assert denied.value.detail == "Permission denied"


def test_anonymous_request_returns_authentication_required() -> None:
    with pytest.raises(HTTPException) as denied:
        enforce_permission(None, Action.READ_PUBLISHED_DATA, ResourceScope(is_published=True))

    assert denied.value.status_code == 401
    assert denied.value.detail == "Authentication required"
