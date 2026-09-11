from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from app.compounds.models import Compound
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision
from app.search.service import text_search_predicate


@dataclass(frozen=True, slots=True)
class PaperListFilters:
    search: str | None = None
    doi: str | None = None
    target: str | None = None
    has_lineage: str | None = None
    relation_status: str | None = None
    structure_state: str | None = None
    review_status: str | None = None
    sort: str = "manifest"


@dataclass(frozen=True, slots=True)
class PublishedPaperRow:
    id: UUID
    revision_id: UUID
    paper_key: str
    doi: str | None
    title: str
    year: str | None
    target: str | None
    review_status: str | None
    manifest_order: int


def _snapshot_text(path: str):
    return ObjectRevision.snapshot["normalized_values"][path].as_string()


def _published_paper_query(release_id: UUID) -> Select:
    return (
        select(
            Paper.id,
            ObjectRevision.id.label("revision_id"),
            Paper.paper_key,
            Paper.doi,
            _snapshot_text("title_guess").label("title"),
            _snapshot_text("filename_year").label("year"),
            _snapshot_text("target").label("target"),
            _snapshot_text("review_status").label("review_status"),
            ReleaseItem.manifest_order,
        )
        .join(
            ReleaseItem,
            (ReleaseItem.object_id == Paper.id)
            & (ReleaseItem.object_kind == ObjectKind.PAPER),
        )
        .join(
            ObjectRevision,
            (ObjectRevision.id == ReleaseItem.revision_id)
            & (ObjectRevision.object_id == Paper.id),
        )
        .where(ReleaseItem.release_id == release_id)
    )


def _release_kind_exists(
    release_id: UUID,
    paper_id: UUID,
    object_kind: ObjectKind,
):
    item = aliased(ReleaseItem)
    return (
        select(1)
        .select_from(item)
        .where(
            item.release_id == release_id,
            item.paper_id == paper_id,
            item.object_kind == object_kind,
        )
        .exists()
    )


def _release_revision_field_exists(
    release_id: UUID,
    paper_id: UUID,
    object_kind: ObjectKind,
    field,
    expected: str,
):
    item = aliased(ReleaseItem)
    revision = aliased(ObjectRevision)
    return (
        select(1)
        .select_from(item)
        .join(
            revision,
            (revision.id == item.revision_id)
            & (revision.object_id == item.object_id),
        )
        .where(
            item.release_id == release_id,
            item.paper_id == paper_id,
            item.object_kind == object_kind,
            field(revision) == expected,
        )
        .exists()
    )


def list_published_papers(
    session: Session,
    release: Release,
    filters: PaperListFilters,
    *,
    page: int,
    page_size: int,
) -> tuple[list[PublishedPaperRow], int]:
    query = _published_paper_query(release.id)
    title = _snapshot_text("title_guess")
    target = _snapshot_text("target")
    review_status = _snapshot_text("review_status")
    if filters.search:
        query = query.where(
            text_search_predicate(
                filters.search,
                Paper.paper_key,
                Paper.doi,
                title,
                ObjectRevision.search_text,
            )
        )
    if filters.doi:
        query = query.where(Paper.doi == filters.doi)
    if filters.target:
        query = query.where(target == filters.target)
    if filters.has_lineage is not None:
        has_lineage = _release_kind_exists(
            release.id,
            Paper.id,
            ObjectKind.LINEAGE,
        )
        query = query.where(
            has_lineage if filters.has_lineage == "true" else ~has_lineage
        )
    if filters.relation_status:
        query = query.where(
            _release_revision_field_exists(
                release.id,
                Paper.id,
                ObjectKind.LINEAGE_EDGE,
                lambda revision: revision.relation_status,
                filters.relation_status,
            )
        )
    if filters.structure_state:
        query = query.where(
            _release_revision_field_exists(
                release.id,
                Paper.id,
                ObjectKind.STRUCTURE,
                lambda revision: revision.structure_state,
                filters.structure_state,
            )
        )
    if filters.review_status:
        query = query.where(review_status == filters.review_status)

    sort_expressions = {
        "manifest": (ReleaseItem.manifest_order.asc(),),
        "paper_id": (Paper.paper_key.asc(),),
        "-paper_id": (Paper.paper_key.desc(),),
        "title": (title.asc(), Paper.paper_key.asc()),
        "-title": (title.desc(), Paper.paper_key.asc()),
    }
    query = query.order_by(*sort_expressions[filters.sort])
    total = int(
        session.scalar(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        or 0
    )
    rows = session.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    ).all()
    return [
        PublishedPaperRow(
            id=row.id,
            revision_id=row.revision_id,
            paper_key=row.paper_key,
            doi=row.doi,
            title=row.title or row.paper_key,
            year=row.year,
            target=row.target,
            review_status=row.review_status,
            manifest_order=row.manifest_order,
        )
        for row in rows
    ], total


def get_published_paper(
    session: Session,
    release: Release,
    paper_id: UUID,
) -> PublishedPaperRow | None:
    row = session.execute(
        _published_paper_query(release.id).where(Paper.id == paper_id)
    ).one_or_none()
    if row is None:
        return None
    return PublishedPaperRow(
        id=row.id,
        revision_id=row.revision_id,
        paper_key=row.paper_key,
        doi=row.doi,
        title=row.title or row.paper_key,
        year=row.year,
        target=row.target,
        review_status=row.review_status,
        manifest_order=row.manifest_order,
    )


def release_items_for_paper(
    session: Session,
    release_id: UUID,
    paper_id: UUID,
) -> list[tuple[ReleaseItem, ObjectRevision]]:
    return list(
        session.execute(
            select(ReleaseItem, ObjectRevision)
            .join(
                ObjectRevision,
                (ObjectRevision.id == ReleaseItem.revision_id)
                & (ObjectRevision.object_id == ReleaseItem.object_id),
            )
            .where(
                ReleaseItem.release_id == release_id,
                ReleaseItem.paper_id == paper_id,
            )
            .order_by(ReleaseItem.manifest_order)
        ).all()
    )


def compounds_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, Compound]:
    if not ids:
        return {}
    return {
        compound.id: compound
        for compound in session.scalars(select(Compound).where(Compound.id.in_(ids)))
    }
