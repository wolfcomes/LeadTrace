from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.activities.models import Activity, ActivityOperator
from app.compounds.models import Compound
from app.evidence.models import EdgeEvidenceLink, Evidence, EvidenceKind, EvidenceRole
from app.lineages.models import (
    Lineage,
    LineageEdge,
    LineageEdgeReviewStatus,
    LineageMember,
    LineageMemberRole,
)
from app.structure_images.models import CropStatus, StructureSourceImage
from app.structures.models import Structure, StructureInputMethod, StructureStatus
from app.workspaces.models import ChangeActorKind


def _compound(aggregate, label: str, order: int = 0) -> Compound:
    return Compound(
        paper_id=aggregate.paper_id,
        workspace_id=aggregate.workspace_id,
        compound_label=label,
        display_name=None,
        description=None,
        sort_order=order,
        created_by_kind=ChangeActorKind.REVIEWER,
    )


def _lineage(aggregate, label: str = "Series A") -> Lineage:
    return Lineage(
        paper_id=aggregate.paper_id,
        workspace_id=aggregate.workspace_id,
        lineage_label=label,
        description=None,
        sort_order=0,
    )


def test_compound_labels_are_unique_within_one_workspace(science_context) -> None:
    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            session.add_all(
                [
                    _compound(science_context.first, "12a"),
                    _compound(science_context.first, "12a"),
                ]
            )
            session.flush()


def test_scientific_rows_cannot_cross_paper_or_workspace(science_context) -> None:
    compound = _compound(science_context.first, "root")
    with science_context.session_factory.begin() as session:
        session.add(compound)
        session.flush()
        compound_id = compound.id

    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            session.add(
                Structure(
                    paper_id=science_context.second.paper_id,
                    workspace_id=science_context.second.workspace_id,
                    compound_id=compound_id,
                    smiles="CCO",
                    canonical_smiles=None,
                    molfile=None,
                    inchi=None,
                    inchikey=None,
                    depiction_asset_id=None,
                    status=StructureStatus.DRAFT,
                    input_method=StructureInputMethod.MANUAL_SMILES,
                )
            )
            session.flush()


def test_compound_has_zero_or_one_current_structure(science_context) -> None:
    compound = _compound(science_context.first, "lead")
    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            session.add(compound)
            session.flush()
            session.add_all(
                [
                    Structure(
                        paper_id=compound.paper_id,
                        workspace_id=compound.workspace_id,
                        compound_id=compound.id,
                        smiles="CCO",
                        status=StructureStatus.DRAFT,
                        input_method=StructureInputMethod.MANUAL_SMILES,
                    ),
                    Structure(
                        paper_id=compound.paper_id,
                        workspace_id=compound.workspace_id,
                        compound_id=compound.id,
                        molfile="molfile",
                        status=StructureStatus.DRAFT,
                        input_method=StructureInputMethod.STRUCTURE_EDITOR,
                    ),
                ]
            )
            session.flush()


def test_lineage_membership_is_unique(science_context) -> None:
    compound = _compound(science_context.first, "member")
    lineage = _lineage(science_context.first)
    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            session.add_all([compound, lineage])
            session.flush()
            session.add_all(
                [
                    LineageMember(
                        paper_id=compound.paper_id,
                        workspace_id=compound.workspace_id,
                        lineage_id=lineage.id,
                        compound_id=compound.id,
                        role=LineageMemberRole.ROOT,
                        sort_order=0,
                    ),
                    LineageMember(
                        paper_id=compound.paper_id,
                        workspace_id=compound.workspace_id,
                        lineage_id=lineage.id,
                        compound_id=compound.id,
                        role=LineageMemberRole.TERMINAL,
                        sort_order=1,
                    ),
                ]
            )
            session.flush()


def _lineage_with_members(session, aggregate):
    parent = _compound(aggregate, "parent")
    child = _compound(aggregate, "child", 1)
    outsider = _compound(aggregate, "outsider", 2)
    lineage = _lineage(aggregate)
    session.add_all([parent, child, outsider, lineage])
    session.flush()
    session.add_all(
        [
            LineageMember(
                paper_id=aggregate.paper_id,
                workspace_id=aggregate.workspace_id,
                lineage_id=lineage.id,
                compound_id=parent.id,
                role=LineageMemberRole.ROOT,
                sort_order=0,
            ),
            LineageMember(
                paper_id=aggregate.paper_id,
                workspace_id=aggregate.workspace_id,
                lineage_id=lineage.id,
                compound_id=child.id,
                role=LineageMemberRole.TERMINAL,
                sort_order=1,
            ),
        ]
    )
    session.flush()
    return lineage, parent, child, outsider


def _edge(aggregate, lineage, parent, child) -> LineageEdge:
    return LineageEdge(
        paper_id=aggregate.paper_id,
        workspace_id=aggregate.workspace_id,
        lineage_id=lineage.id,
        parent_compound_id=parent.id,
        child_compound_id=child.id,
        relation_type="optimization",
        modification_summary=None,
        review_status=LineageEdgeReviewStatus.DRAFT,
        sort_order=0,
    )


def test_lineage_edge_rejects_self_loop(science_context) -> None:
    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            lineage, parent, _, _ = _lineage_with_members(
                session, science_context.first
            )
            session.add(_edge(science_context.first, lineage, parent, parent))
            session.flush()


def test_lineage_rejects_duplicate_directed_edge(science_context) -> None:
    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            lineage, parent, child, _ = _lineage_with_members(
                session, science_context.first
            )
            session.add_all(
                [
                    _edge(science_context.first, lineage, parent, child),
                    _edge(science_context.first, lineage, parent, child),
                ]
            )
            session.flush()


def test_edge_endpoints_must_be_members_of_the_lineage(science_context) -> None:
    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            lineage, parent, _, outsider = _lineage_with_members(
                session, science_context.first
            )
            session.add(_edge(science_context.first, lineage, parent, outsider))
            session.flush()


@pytest.mark.parametrize(
    ("x0", "y0", "x1", "y1"),
    [
        (Decimal("-0.1"), Decimal("0.1"), Decimal("0.5"), Decimal("0.5")),
        (Decimal("0.1"), Decimal("0.1"), Decimal("1.1"), Decimal("0.5")),
        (Decimal("0.5"), Decimal("0.1"), Decimal("0.5"), Decimal("0.5")),
        (Decimal("0.1"), Decimal("0.5"), Decimal("0.5"), Decimal("0.5")),
    ],
)
def test_structure_source_image_rejects_invalid_normalized_bbox(
    science_context,
    x0: Decimal,
    y0: Decimal,
    x1: Decimal,
    y1: Decimal,
) -> None:
    compound = _compound(science_context.first, "image")
    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            session.add(compound)
            session.flush()
            session.add(
                StructureSourceImage(
                    paper_id=compound.paper_id,
                    workspace_id=compound.workspace_id,
                    compound_id=compound.id,
                    source_sha256="1" * 64,
                    page_number=1,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    source_context=None,
                    label=None,
                    reviewer_note=None,
                    crop_status=CropStatus.PENDING,
                    crop_asset_id=None,
                )
            )
            session.flush()


@pytest.mark.parametrize(
    ("x0", "y0", "x1", "y1"),
    [
        (None, Decimal("0.1"), Decimal("0.5"), Decimal("0.5")),
        (Decimal("0.1"), Decimal("0.1"), Decimal("1.1"), Decimal("0.5")),
    ],
)
def test_evidence_rejects_partial_or_invalid_normalized_bbox(
    science_context,
    x0: Decimal | None,
    y0: Decimal | None,
    x1: Decimal | None,
    y1: Decimal | None,
) -> None:
    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            session.add(
                Evidence(
                    paper_id=science_context.first.paper_id,
                    workspace_id=science_context.first.workspace_id,
                    kind=EvidenceKind.IMAGE,
                    source_sha256="1" * 64,
                    page_number=1,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    quoted_text=None,
                    caption=None,
                    crop_asset_id=None,
                    reviewer_note=None,
                )
            )
            session.flush()


def test_edge_evidence_link_cannot_cross_workspace(science_context) -> None:
    with science_context.session_factory.begin() as session:
        lineage, parent, child, _ = _lineage_with_members(
            session, science_context.first
        )
        edge = _edge(science_context.first, lineage, parent, child)
        session.add(edge)
        other_evidence = Evidence(
            paper_id=science_context.second.paper_id,
            workspace_id=science_context.second.workspace_id,
            kind=EvidenceKind.TEXT,
            source_sha256="2" * 64,
            page_number=1,
            x0=None,
            y0=None,
            x1=None,
            y1=None,
            quoted_text="Other Paper evidence",
            caption=None,
            crop_asset_id=None,
            reviewer_note=None,
        )
        session.add(other_evidence)
        session.flush()
        edge_id = edge.id
        evidence_id = other_evidence.id

    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            session.add(
                EdgeEvidenceLink(
                    paper_id=science_context.first.paper_id,
                    workspace_id=science_context.first.workspace_id,
                    edge_id=edge_id,
                    evidence_id=evidence_id,
                    role=EvidenceRole.SUPPORTS,
                )
            )
            session.flush()


def test_activity_references_compound_and_optional_evidence_in_same_workspace(
    science_context,
) -> None:
    with science_context.session_factory.begin() as session:
        compound = _compound(science_context.first, "active")
        evidence = Evidence(
            paper_id=science_context.first.paper_id,
            workspace_id=science_context.first.workspace_id,
            kind=EvidenceKind.TABLE,
            source_sha256="1" * 64,
            page_number=2,
            quoted_text="IC50 = 12 nM",
        )
        session.add_all([compound, evidence])
        session.flush()
        activity = Activity(
            paper_id=science_context.first.paper_id,
            workspace_id=science_context.first.workspace_id,
            compound_id=compound.id,
            evidence_id=evidence.id,
            assay_name="Cellular assay",
            metric="IC50",
            operator=ActivityOperator.EQUAL,
            value=Decimal("12"),
            unit="nM",
            context="Reported in Table 2",
            sort_order=0,
        )
        session.add(activity)
        session.flush()

        assert activity.id is not None


def test_activity_reference_prevents_compound_deletion(science_context) -> None:
    with science_context.session_factory.begin() as session:
        compound = _compound(science_context.first, "referenced")
        session.add(compound)
        session.flush()
        session.add(
            Activity(
                paper_id=compound.paper_id,
                workspace_id=compound.workspace_id,
                compound_id=compound.id,
                evidence_id=None,
                assay_name="Binding assay",
                metric="Ki",
                operator=ActivityOperator.LESS_THAN,
                value=Decimal("5"),
                unit="nM",
                context=None,
                sort_order=0,
            )
        )
        session.flush()
        compound_id = compound.id

    with pytest.raises(IntegrityError):
        with science_context.session_factory.begin() as session:
            persisted = session.get(Compound, compound_id)
            assert persisted is not None
            session.delete(persisted)
            session.flush()
