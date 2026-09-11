from __future__ import annotations

from app.revisions.models import ObjectRevision


def test_review_revision_foreign_key_breaks_metadata_sort_cycle() -> None:
    constraint = next(
        constraint
        for constraint in ObjectRevision.__table__.foreign_key_constraints
        if constraint.name == "fk_object_revisions_changeset_item"
    )

    assert constraint.use_alter is True
