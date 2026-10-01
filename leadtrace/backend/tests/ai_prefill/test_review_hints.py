"""Review hints are annotations, never a replacement for scientific review."""
import pytest
from sqlalchemy import select

from app.activities.models import Activity
from app.activities.schemas import ActivityUpdateRequest
from app.activities.service import ActivityService
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.service import AiPrefillService
from app.compounds.models import Compound
from app.compounds.schemas import CompoundUpdateRequest
from app.compounds.service import CompoundService
from app.lineages.models import LineageEdge, LineageEdgeReviewStatus
from app.lineages.schemas import LineageEdgeUpdateRequest
from app.lineages.service import LineageService
from app.publications.schemas import PublishedPaperSnapshotResponse
from app.security.policies import Principal
from app.structures.models import Structure, StructureStatus
from app.users.models import UserRole
from app.workspaces.models import ChangeEvent, PaperWorkspace
from app.workspaces.service import WorkspaceVersionConflictError
from app.workspaces.snapshot import build_paper_snapshot

from .test_apply import ai_context, _queue
from .test_contract import complete_payload


def test_import_snapshot_and_clear_hints_with_versioned_history(ai_context):
    raw = complete_payload()
    for row in [raw['compounds'][0], raw['activities'][0], raw['lineages'][0]['edges'][0]]:
        row['review_hint'] = 'Source supports this candidate; verify correspondence.'
    with ai_context.session_factory.begin() as session:
        AiPrefillService().apply(session, run_id=_queue(ai_context), payload=AiPrefillPayload.model_validate(raw))
    actor = Principal(ai_context.reviewer_id, UserRole.REVIEWER)
    with ai_context.session_factory.begin() as session:
        compound = session.scalar(select(Compound).where(Compound.compound_label == 'Lead 1'))
        activity = session.scalar(select(Activity))
        edge = session.scalar(select(LineageEdge))
        ids = compound.id, activity.id, edge.id
        assert compound.review_hint == activity.review_hint == edge.review_hint == raw['compounds'][0]['review_hint']
        assert edge.review_status == LineageEdgeReviewStatus.DRAFT
        assert all(s.status == StructureStatus.DRAFT for s in session.scalars(select(Structure)))
        snapshot = build_paper_snapshot(session, ai_context.workspace_id)
        published = PublishedPaperSnapshotResponse.model_validate(snapshot)
        assert next(c for c in published.compounds if c.id == compound.id).review_hint == compound.review_hint
        assert published.activities[0].review_hint == activity.review_hint
        assert published.lineage_edges[0].review_hint == edge.review_hint
        assert 'review_hint' not in next(c for c in snapshot['compounds'] if c['id'] != str(compound.id))
    operations = [
        (CompoundService().update_compound, 'compound_id', CompoundUpdateRequest),
        (ActivityService().update_activity, 'activity_id', ActivityUpdateRequest),
        (LineageService().update_edge, 'edge_id', LineageEdgeUpdateRequest),
    ]
    for version, (entity_id, (update, key, schema)) in enumerate(zip(ids, operations), 2):
        with ai_context.session_factory.begin() as session:
            with pytest.raises(WorkspaceVersionConflictError):
                update(session, **{key: entity_id}, expected_version=version-1, actor=actor, updates={'review_hint': None})
        request = schema(expected_workspace_version=version, review_hint=None)
        with ai_context.session_factory.begin() as session:
            update(session, **{key: entity_id}, expected_version=version, actor=actor, updates=request.updates())
    with ai_context.session_factory() as session:
        assert session.get(PaperWorkspace, ai_context.workspace_id).version == 5
        snapshot = build_paper_snapshot(session, ai_context.workspace_id)
        assert all('review_hint' not in row for name in ['compounds', 'activities', 'lineage_edges'] for row in snapshot[name])
        assert all(row.review_hint is None for row in PublishedPaperSnapshotResponse.model_validate(snapshot).compounds)
        edits = session.scalars(select(ChangeEvent).where(ChangeEvent.action.in_(['compound.update','activity.update','lineage_edge.update']))).all()
        assert len(edits) == 3
        assert all(row.before_value['review_hint'] and not row.after_value.get('review_hint') for row in edits)
