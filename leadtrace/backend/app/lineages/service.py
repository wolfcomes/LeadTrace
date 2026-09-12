from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.lineages.models import Lineage, LineageEdge
from app.lineages.validation import LineageValidationError, validate_lineage_edge_input
from app.revisions.models import ObjectRevision, StructureState
from app.science.common import (
    ScientificVersionConflict,
    create_draft_revision,
    editable_changeset,
    ensure_changeset_item,
    latest_revision,
)
from app.structures.models import Structure


class LineageVersionConflict(ScientificVersionConflict):
    pass


@dataclass(frozen=True, slots=True)
class PairReadiness:
    eligible: bool
    blocking_codes: tuple[str, ...]


class PairReadinessService:
    """Derive pair eligibility from current scientific facts, never client input."""

    @staticmethod
    def from_facts(
        *,
        relation_status: str,
        parent_id: UUID | str | None,
        derived_id: UUID | str | None,
        parent_structure_state: str | None,
        derived_structure_state: str | None,
        parent_smiles: str | None,
        derived_smiles: str | None,
        evidence_ids: tuple[UUID | str, ...],
    ) -> PairReadiness:
        blockers: list[str] = []
        if relation_status not in {"text_explicit", "figure_explicit", "human_confirmed"}:
            blockers.append("UNCONFIRMED_RELATION")
        if parent_id is None:
            blockers.append("UNRESOLVED_PARENT")
        if derived_id is None:
            blockers.append("MISSING_DERIVED_COMPOUND")
        if parent_id is not None and derived_id is not None and parent_id == derived_id:
            blockers.append("SELF_LOOP")
        if parent_structure_state != StructureState.STRUCTURE_CONFIRMED.value:
            blockers.append("MISSING_PARENT_STRUCTURE")
        if derived_structure_state != StructureState.STRUCTURE_CONFIRMED.value:
            blockers.append("MISSING_DERIVED_STRUCTURE")
        if not parent_smiles:
            blockers.append("MISSING_PARENT_SMILES")
        if not derived_smiles:
            blockers.append("MISSING_DERIVED_SMILES")
        if not evidence_ids:
            blockers.append("MISSING_EVIDENCE")
        unique_blockers = tuple(dict.fromkeys(blockers))
        return PairReadiness(not unique_blockers, unique_blockers)

    @classmethod
    def from_database(cls, session: Session, edge_id: UUID) -> PairReadiness:
        edge = session.get(LineageEdge, edge_id)
        if edge is None:
            raise ValueError("Lineage edge not found")
        revision = latest_revision(session, edge.id)
        if revision is None:
            raise ValueError("Lineage edge has no revision")
        if revision.is_tombstone:
            return PairReadiness(False, ("DELETED_EDGE",))
        snapshot = revision.snapshot
        parent_id = _snapshot_uuid(snapshot.get("parent_compound_id"))
        derived_id = _snapshot_uuid(snapshot.get("derived_compound_id"))
        relation_status = str(snapshot.get("relation_status") or revision.relation_status or "")
        evidence_ids = _snapshot_uuids(snapshot.get("evidence_ids"))
        valid_evidence: list[UUID] = []
        for evidence_id in evidence_ids:
            evidence = session.get(Evidence, evidence_id)
            if evidence is None or evidence.paper_id != edge.paper_id:
                continue
            evidence_revision = latest_revision(session, evidence.id)
            if evidence_revision is None or evidence_revision.is_tombstone:
                continue
            valid_evidence.append(evidence_id)

        parent_state, parent_smiles = _structure_facts(session, edge.paper_id, parent_id)
        derived_state, derived_smiles = _structure_facts(session, edge.paper_id, derived_id)
        return cls.from_facts(
            relation_status=relation_status,
            parent_id=parent_id,
            derived_id=derived_id,
            parent_structure_state=parent_state,
            derived_structure_state=derived_state,
            parent_smiles=parent_smiles,
            derived_smiles=derived_smiles,
            evidence_ids=tuple(valid_evidence),
        )


def _snapshot_uuid(value: object) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


def _snapshot_uuids(value: object) -> tuple[UUID, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[UUID] = []
    for item in value:
        parsed = _snapshot_uuid(item)
        if parsed is not None:
            result.append(parsed)
    return tuple(result)


def _structure_facts(
    session: Session,
    paper_id: UUID,
    compound_id: UUID | None,
) -> tuple[str | None, str | None]:
    if compound_id is None:
        return None, None
    structures = session.scalars(
        select(Structure).where(
            Structure.paper_id == paper_id,
            Structure.compound_id == compound_id,
        )
    )
    for structure in structures:
        revision = latest_revision(session, structure.id)
        if revision is None or revision.is_tombstone:
            continue
        state = revision.structure_state.value if revision.structure_state else None
        smiles = revision.canonical_smiles
        if state == StructureState.STRUCTURE_CONFIRMED.value and smiles:
            return state, smiles
    return None, None


class LineageReviewService:
    """Persist lineage identities and edges as append-only scientific revisions."""

    @staticmethod
    def _required(value: str, field: str) -> str:
        clean = value.strip()
        if not clean:
            raise LineageValidationError(f"{field} is required")
        if len(clean) > 255:
            raise LineageValidationError(f"{field} must be at most 255 characters")
        return clean

    @staticmethod
    def _lineage_snapshot(lineage: Lineage) -> dict[str, object]:
        return {"lineage_key": lineage.lineage_key, "paper_id": str(lineage.paper_id)}

    @staticmethod
    def _edge_snapshot(
        *,
        edge: LineageEdge,
        parent_compound_id: UUID | None,
        derived_compound_id: UUID,
        relation_type: str,
        relation_status: str,
        evidence_ids: tuple[UUID, ...],
    ) -> dict[str, object]:
        return {
            "edge_key": edge.edge_key,
            "paper_id": str(edge.paper_id),
            "lineage_id": str(edge.lineage_id),
            "parent_compound_id": str(parent_compound_id) if parent_compound_id else None,
            "derived_compound_id": str(derived_compound_id),
            "relation_type": relation_type,
            "relation_status": relation_status,
            "evidence_ids": [str(item) for item in evidence_ids],
        }

    @staticmethod
    def _validate_scope(
        session: Session,
        *,
        paper_id: UUID,
        lineage_id: UUID,
        parent_compound_id: UUID | None,
        derived_compound_id: UUID,
        evidence_ids: tuple[UUID, ...],
    ) -> Lineage:
        lineage = session.scalar(select(Lineage).where(Lineage.id == lineage_id))
        if lineage is None or lineage.paper_id != paper_id:
            raise LineageValidationError("Lineage does not belong to this Paper")
        derived = session.get(Compound, derived_compound_id)
        parent = session.get(Compound, parent_compound_id) if parent_compound_id else None
        if derived is None or derived.paper_id != paper_id:
            raise LineageValidationError("Derived compound must belong to this Paper")
        if parent_compound_id is not None and (parent is None or parent.paper_id != paper_id):
            raise LineageValidationError("Parent compound must belong to this Paper")
        evidence = session.scalars(select(Evidence).where(Evidence.id.in_(evidence_ids))).all()
        if len(evidence) != len(evidence_ids) or any(item.paper_id != paper_id for item in evidence):
            raise LineageValidationError("Lineage evidence must belong to this Paper")
        return lineage

    @staticmethod
    def _ensure_unique_relation(
        session: Session,
        *,
        paper_id: UUID,
        lineage_id: UUID,
        parent_compound_id: UUID | None,
        derived_compound_id: UUID,
        exclude_edge_id: UUID | None = None,
    ) -> None:
        statement = select(LineageEdge).where(
            LineageEdge.paper_id == paper_id,
            LineageEdge.lineage_id == lineage_id,
            LineageEdge.derived_compound_id == derived_compound_id,
        )
        if parent_compound_id is None:
            statement = statement.where(LineageEdge.parent_compound_id.is_(None))
        else:
            statement = statement.where(LineageEdge.parent_compound_id == parent_compound_id)
        if exclude_edge_id is not None:
            statement = statement.where(LineageEdge.id != exclude_edge_id)
        for candidate in session.scalars(statement):
            revision = latest_revision(session, candidate.id)
            if revision is None or not revision.is_tombstone:
                raise LineageValidationError("duplicate lineage edge is not allowed")

    def create_lineage(
        self,
        session: Session,
        *,
        paper_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        lineage_key: str,
        reason: str,
    ) -> tuple[Lineage, ObjectRevision]:
        key = self._required(lineage_key, "lineage_key")
        clean_reason = self._required(reason, "reason")
        changeset = editable_changeset(session, changeset_id=changeset_id, expected_version=expected_version, paper_id=paper_id, conflict_type=LineageVersionConflict)
        if session.scalar(select(Lineage.id).where(Lineage.paper_id == paper_id, Lineage.lineage_key == key)) is not None:
            raise LineageValidationError("lineage_key already exists for this Paper")
        lineage = Lineage(paper_id=paper_id, lineage_key=key)
        session.add(lineage)
        session.flush()
        snapshot = self._lineage_snapshot(lineage)
        item = ensure_changeset_item(session, changeset=changeset, object_id=lineage.id, object_kind="lineage", snapshot=snapshot, base_revision_id=None)
        revision = create_draft_revision(session, object_identity=lineage, actor_id=actor_id, reason=clean_reason, snapshot=snapshot, changeset=changeset, predecessor=None)
        item.proposed_revision_id = revision.id
        session.flush()
        return lineage, revision

    def create_edge(
        self,
        session: Session,
        *,
        paper_id: UUID,
        lineage_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        edge_key: str,
        parent_compound_id: UUID | None,
        derived_compound_id: UUID,
        relation_type: str,
        relation_status: str,
        evidence_ids: tuple[UUID, ...],
        reason: str,
        pair_ready: bool | None = None,
    ) -> tuple[LineageEdge, ObjectRevision]:
        edge_key = self._required(edge_key, "edge_key")
        clean_reason = self._required(reason, "reason")
        validated = validate_lineage_edge_input(
            paper_id=paper_id,
            parent_compound_id=parent_compound_id,
            derived_compound_id=derived_compound_id,
            relation_status=relation_status,
            relation_type=relation_type,
            evidence_ids=evidence_ids,
            pair_ready=pair_ready,
        )
        lineage = self._validate_scope(
            session,
            paper_id=paper_id,
            lineage_id=lineage_id,
            parent_compound_id=validated.parent_compound_id,
            derived_compound_id=validated.derived_compound_id,
            evidence_ids=validated.evidence_ids,
        )
        self._ensure_unique_relation(
            session,
            paper_id=paper_id,
            lineage_id=lineage.id,
            parent_compound_id=validated.parent_compound_id,
            derived_compound_id=validated.derived_compound_id,
        )
        changeset = editable_changeset(session, changeset_id=changeset_id, expected_version=expected_version, paper_id=paper_id, conflict_type=LineageVersionConflict)
        if session.scalar(select(LineageEdge.id).where(LineageEdge.paper_id == paper_id, LineageEdge.edge_key == edge_key)) is not None:
            raise LineageValidationError("edge_key already exists for this Paper")
        edge = LineageEdge(
            paper_id=paper_id,
            lineage_id=lineage.id,
            edge_key=edge_key,
            parent_compound_id=validated.parent_compound_id,
            derived_compound_id=validated.derived_compound_id,
        )
        session.add(edge)
        session.flush()
        snapshot = self._edge_snapshot(edge=edge, parent_compound_id=validated.parent_compound_id, derived_compound_id=validated.derived_compound_id, relation_type=validated.relation_type, relation_status=validated.relation_status, evidence_ids=validated.evidence_ids)
        item = ensure_changeset_item(session, changeset=changeset, object_id=edge.id, object_kind="lineage_edge", snapshot=snapshot, base_revision_id=None)
        revision = create_draft_revision(session, object_identity=edge, actor_id=actor_id, reason=clean_reason, snapshot=snapshot, changeset=changeset, predecessor=None, relation_type=validated.relation_type, relation_status=validated.relation_status)
        item.proposed_revision_id = revision.id
        session.flush()
        return edge, revision

    def update_edge(
        self,
        session: Session,
        *,
        edge_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        parent_compound_id: UUID | None,
        derived_compound_id: UUID,
        relation_type: str,
        relation_status: str,
        evidence_ids: tuple[UUID, ...],
        reason: str,
        pair_ready: bool | None = None,
    ) -> ObjectRevision:
        edge = session.scalar(select(LineageEdge).where(LineageEdge.id == edge_id).with_for_update())
        if edge is None:
            raise LineageValidationError("Lineage edge not found")
        clean_reason = self._required(reason, "reason")
        validated = validate_lineage_edge_input(paper_id=edge.paper_id, parent_compound_id=parent_compound_id, derived_compound_id=derived_compound_id, relation_status=relation_status, relation_type=relation_type, evidence_ids=evidence_ids, pair_ready=pair_ready)
        self._validate_scope(session, paper_id=edge.paper_id, lineage_id=edge.lineage_id, parent_compound_id=validated.parent_compound_id, derived_compound_id=validated.derived_compound_id, evidence_ids=validated.evidence_ids)
        self._ensure_unique_relation(session, paper_id=edge.paper_id, lineage_id=edge.lineage_id, parent_compound_id=validated.parent_compound_id, derived_compound_id=validated.derived_compound_id, exclude_edge_id=edge.id)
        changeset = editable_changeset(session, changeset_id=changeset_id, expected_version=expected_version, paper_id=edge.paper_id, conflict_type=LineageVersionConflict)
        previous = latest_revision(session, edge.id, for_update=True)
        if previous is None:
            raise LineageValidationError("Lineage edge has no revision")
        if previous.is_tombstone:
            raise LineageValidationError("Lineage edge is deleted")
        snapshot = self._edge_snapshot(edge=edge, parent_compound_id=validated.parent_compound_id, derived_compound_id=validated.derived_compound_id, relation_type=validated.relation_type, relation_status=validated.relation_status, evidence_ids=validated.evidence_ids)
        item = ensure_changeset_item(session, changeset=changeset, object_id=edge.id, object_kind="lineage_edge", snapshot=previous.snapshot, base_revision_id=previous.id)
        revision = create_draft_revision(session, object_identity=edge, actor_id=actor_id, reason=clean_reason, snapshot=snapshot, changeset=changeset, predecessor=previous, relation_type=validated.relation_type, relation_status=validated.relation_status)
        edge.parent_compound_id = validated.parent_compound_id
        edge.derived_compound_id = validated.derived_compound_id
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        session.flush()
        return revision

    def delete_edge(
        self,
        session: Session,
        *,
        edge_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        reason: str,
    ) -> ObjectRevision:
        edge = session.scalar(select(LineageEdge).where(LineageEdge.id == edge_id).with_for_update())
        if edge is None:
            raise LineageValidationError("Lineage edge not found")
        clean_reason = self._required(reason, "reason")
        changeset = editable_changeset(session, changeset_id=changeset_id, expected_version=expected_version, paper_id=edge.paper_id, conflict_type=LineageVersionConflict)
        previous = latest_revision(session, edge.id, for_update=True)
        if previous is None:
            raise LineageValidationError("Lineage edge has no revision")
        if previous.is_tombstone:
            raise LineageValidationError("Lineage edge is already deleted")
        downstream = session.scalars(select(LineageEdge).where(LineageEdge.paper_id == edge.paper_id, LineageEdge.parent_compound_id == edge.derived_compound_id, LineageEdge.id != edge.id)).all()
        for candidate in downstream:
            candidate_revision = latest_revision(session, candidate.id)
            if candidate_revision is not None and not candidate_revision.is_tombstone:
                raise LineageValidationError("Deleting this edge would leave a dangling lineage relation")
        snapshot = dict(previous.snapshot)
        snapshot["deleted"] = True
        item = ensure_changeset_item(session, changeset=changeset, object_id=edge.id, object_kind="lineage_edge", snapshot=previous.snapshot, base_revision_id=previous.id)
        revision = create_draft_revision(session, object_identity=edge, actor_id=actor_id, reason=clean_reason, snapshot=snapshot, changeset=changeset, predecessor=previous, relation_type=previous.relation_type, relation_status=previous.relation_status, is_tombstone=True)
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        session.flush()
        return revision
