from __future__ import annotations

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind
from tests.api.conftest import PublishedApiFixture


def test_release_item_must_pair_an_object_with_its_own_revision(
    published_api: PublishedApiFixture,
) -> None:
    with pytest.raises(IntegrityError):
        with published_api.session_factory.begin() as session:
            session.add(
                ReleaseItem(
                    release_id=published_api.release_id,
                    object_id=published_api.unpublished_paper_id,
                    revision_id=published_api.draft_revision_id,
                    paper_id=published_api.unpublished_paper_id,
                    object_kind=ObjectKind.PAPER,
                    manifest_order=999,
                )
            )


def test_release_manifest_items_are_append_only(
    published_api: PublishedApiFixture,
) -> None:
    with published_api.session_factory() as session:
        item_id = session.scalar(
            select(ReleaseItem.id).where(
                ReleaseItem.release_id == published_api.release_id
            )
        )
        assert item_id is not None

    with pytest.raises(DBAPIError, match="release item is immutable"):
        with published_api.session_factory.begin() as session:
            session.execute(
                update(ReleaseItem)
                .where(ReleaseItem.id == item_id)
                .values(manifest_order=999)
            )

    with pytest.raises(DBAPIError, match="release item is immutable"):
        with published_api.session_factory.begin() as session:
            session.execute(delete(ReleaseItem).where(ReleaseItem.id == item_id))


def test_published_release_metadata_is_immutable(
    published_api: PublishedApiFixture,
) -> None:
    with pytest.raises(DBAPIError, match="release is immutable"):
        with published_api.session_factory.begin() as session:
            session.execute(
                update(Release)
                .where(Release.id == published_api.release_id)
                .values(title="Retitled after publication")
            )
