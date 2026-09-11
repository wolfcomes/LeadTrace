from __future__ import annotations

from datetime import UTC, datetime
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind
from app.users.models import User, UserRole
from tests.api.conftest import PublishedApiFixture


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


def test_finalized_release_manifest_rejects_append(
    published_api: PublishedApiFixture,
) -> None:
    with pytest.raises(DBAPIError, match="release manifest is finalized"):
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


def test_release_item_must_pair_an_object_with_its_own_revision(
    published_api: PublishedApiFixture,
) -> None:
    with pytest.raises(DBAPIError, match="release item revision is not published"):
        with published_api.session_factory.begin() as session:
            admin_id = session.scalar(select(User.id).where(User.role == UserRole.ADMIN))
            release = Release(
                release_key="unfinalized-revision-check",
                title="Revision check",
                notes="",
                metrics={},
                published_by_id=admin_id,
                published_at=datetime(2026, 9, 11, 1, 0, tzinfo=UTC),
                is_current=False,
                manifest_finalized=False,
            )
            session.add(release)
            session.flush()
            session.add(
                ReleaseItem(
                    release_id=release.id,
                    object_id=published_api.unpublished_paper_id,
                    revision_id=published_api.draft_revision_id,
                    paper_id=published_api.unpublished_paper_id,
                    object_kind=ObjectKind.PAPER,
                    manifest_order=1002,
                )
            )


def test_release_item_rejects_wrong_declared_object_kind(
    published_api: PublishedApiFixture,
) -> None:
    with pytest.raises(DBAPIError, match="object kind does not match"):
        with published_api.session_factory.begin() as session:
            admin_id = session.scalar(select(User.id).where(User.role == UserRole.ADMIN))
            release = Release(
                release_key="unfinalized-kind-check",
                title="Kind check",
                notes="",
                metrics={},
                published_by_id=admin_id,
                published_at=datetime(2026, 9, 11, 1, 0, tzinfo=UTC),
                is_current=False,
                manifest_finalized=False,
            )
            session.add(release)
            session.flush()
            session.add(
                ReleaseItem(
                    release_id=release.id,
                    object_id=published_api.detail_paper_id,
                    revision_id=published_api.published_revision_id,
                    paper_id=published_api.detail_paper_id,
                    object_kind=ObjectKind.COMPOUND,
                    manifest_order=1001,
                )
            )


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
