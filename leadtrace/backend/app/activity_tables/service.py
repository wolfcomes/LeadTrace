from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from app.activities.models import Activity
from app.activity_tables.models import ActivityTable
from app.activity_tables.schemas import TableDefinition, TableResponse
from app.api.errors import APIError
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.compounds.models import Compound
from app.evidence.models import Evidence, EvidenceKind
from app.papers.models import Paper
from app.workspaces.history import MutationChange
from app.workspaces.models import PaperWorkspace
from app.workspaces.service import WorkspaceNotFoundError, WorkspaceService


def table_snapshot(row):
    data = TableResponse.model_validate(row, from_attributes=True).model_dump(mode='json')
    # Optional additions must not change historical snapshot hashes.
    if data['compound_ids'] is None:
        data.pop('compound_ids')
    if not data['evidence_ids']:
        data.pop('evidence_ids')
    return data


def validate_table_references(session, workspace_id, columns, paper_id=None, compound_ids=None, evidence_ids=None):
    """Validate explicit identities; a display label never changes membership."""
    ids = {UUID(str(item)) for column in columns for item in column['activity_ids']}
    rows = {row.id: row for row in session.scalars(select(Activity).where(
        Activity.workspace_id == workspace_id, Activity.id.in_(ids)))}
    if set(rows) != ids:
        raise APIError(422, 'ACTIVITY_TABLE_INVALID', 'Every Activity must belong to this Workspace')
    if compound_ids is not None:
        compounds = {UUID(str(item)) for item in compound_ids}
        found = set(session.scalars(select(Compound.id).where(Compound.workspace_id == workspace_id, Compound.id.in_(compounds))))
        if len(compounds) != len(compound_ids) or found != compounds or any(row.compound_id not in compounds for row in rows.values()):
            raise APIError(422, 'ACTIVITY_TABLE_INVALID', 'Table rows must belong to this Workspace and contain every linked Activity')
    if evidence_ids is not None:
        validate_table_evidence(session, workspace_id, evidence_ids, paper_id=paper_id)
    for column in columns:
        for item in column['activity_ids']:
            row = rows[UUID(str(item))]
            if (row.assay_name, row.metric, row.unit) != (column['assay'], column['metric'], column.get('unit')) or (paper_id is not None and row.paper_id != paper_id):
                raise APIError(422, 'ACTIVITY_TABLE_INVALID', 'Column measurement must exactly match every linked Activity')


def validate_table_evidence(session, workspace_id, evidence_ids, *, paper_id=None, require_image=False):
    ids = [UUID(str(item)) for item in evidence_ids]
    if require_image and not ids:
        raise APIError(422, 'ACTIVITY_TABLE_EVIDENCE_REQUIRED', 'Original source tables require a Table screenshot before confirmation')
    if not ids:
        return
    rows = list(session.scalars(select(Evidence).where(Evidence.workspace_id == workspace_id, Evidence.id.in_(ids))))
    workspace = session.get(PaperWorkspace, workspace_id)
    paper = session.get(Paper, paper_id or workspace.paper_id)
    source = session.get(PaperSource, paper.source_id)
    if len(set(ids)) != len(ids) or len(rows) != len(ids) or any(
        row.paper_id != paper.id or row.kind != EvidenceKind.TABLE or row.x0 is None
        or source.integrity_state != PaperSourceIntegrityState.VERIFIED
        or row.source_sha256 != source.sha256 or not 1 <= row.page_number <= source.page_count
        for row in rows
    ):
        raise APIError(422, 'ACTIVITY_TABLE_INVALID', 'Table Evidence must have a valid screenshot from this Paper Source')


def reconcile_activity_tables(session, workspace_id, changed_activity_ids=()):
    """Prune removed/reclassified records, and invalidate affected confirmations.

    Caller must include these changes in its existing audited transaction.
    Returns before/after table snapshots for provenance-aware callers.
    """
    session.flush()
    activities = {str(r.id): r for r in session.scalars(select(Activity).where(Activity.workspace_id == workspace_id))}
    changed = {str(x) for x in changed_activity_ids}
    deltas = []
    for row in session.scalars(select(ActivityTable).where(ActivityTable.workspace_id == workspace_id)):
        before = table_snapshot(row)
        columns = deepcopy(row.columns)
        affected = False
        for column in columns:
            kept = []
            for aid in column['activity_ids']:
                activity = activities.get(aid)
                if activity and (activity.assay_name, activity.metric, activity.unit) == (column['assay'], column['metric'], column.get('unit')):
                    kept.append(aid)
                else:
                    affected = True
                affected = affected or aid in changed
            column['activity_ids'] = kept
        if affected:
            row.columns = columns
            row.review_status = 'draft'
            after = table_snapshot(row)
            if before != after:
                deltas.append((before, after))
    session.flush()
    return deltas


class ActivityTableService:
    def __init__(self):
        self.workspace_service = WorkspaceService()

    def listing(self, session, workspace_id, actor):
        self.workspace_service.get_workspace(session, workspace_id=workspace_id, actor=actor)
        # Shared workspace row lock gives version, table links and Other one
        # consistent boundary without creating a viewing receipt.
        workspace = session.scalar(select(PaperWorkspace).where(PaperWorkspace.id == workspace_id).with_for_update(read=True).execution_options(populate_existing=True))
        rows = list(session.scalars(select(ActivityTable).where(ActivityTable.workspace_id == workspace_id).order_by(ActivityTable.created_at, ActivityTable.id)))
        assigned = {aid for row in rows for column in row.columns for aid in column['activity_ids']}
        ids = session.scalars(select(Activity.id).where(Activity.workspace_id == workspace_id).order_by(Activity.id))
        return dict(workspace_id=workspace_id, workspace_version=workspace.version,
                    tables=[table_snapshot(row) for row in rows], other_activity_ids=[aid for aid in ids if str(aid) not in assigned])

    def mutate(self, session, workspace_id, table_id, actor, version, values=None, delete=False, confirm=None):
        output = {}
        def mutation(context):
            row = session.get(ActivityTable, table_id)
            if row is not None and row.workspace_id != workspace_id:
                raise WorkspaceNotFoundError('Resource not found')
            if row is None and (delete or confirm is not None):
                raise WorkspaceNotFoundError('Resource not found')
            before = table_snapshot(row) if row else None
            if delete:
                session.delete(row)
                return MutationChange('activity_table', table_id, 'activity_table.delete', before, None)
            if confirm is not None:
                if not row.columns:
                    raise APIError(422, 'ACTIVITY_TABLE_INVALID', 'Add at least one column before confirming a table')
                validate_table_references(session, workspace_id, row.columns, context.workspace.paper_id, row.compound_ids, row.evidence_ids)
                if confirm == 'reviewer_confirmed' and row.kind == 'source':
                    validate_table_evidence(session, workspace_id, row.evidence_ids, paper_id=context.workspace.paper_id, require_image=True)
                row.review_status = confirm
                action = 'activity_table.confirm'
            else:
                data = TableDefinition.model_validate(values).model_dump(mode='json')
                validate_table_references(session, workspace_id, data['columns'], context.workspace.paper_id, data['compound_ids'], data['evidence_ids'])
                if data['page_number'] is not None:
                    paper = session.get(Paper, context.workspace.paper_id)
                    source = session.get(PaperSource, paper.source_id)
                    if data['page_number'] > source.page_count:
                        raise APIError(422, 'ACTIVITY_TABLE_INVALID', 'Table page exceeds the source document')
                if row is None:
                    row = ActivityTable(id=table_id, workspace_id=workspace_id, paper_id=context.workspace.paper_id,
                                        created_by_kind='reviewer', review_status='draft', **data)
                    session.add(row)
                    action = 'activity_table.create'
                else:
                    if any(getattr(row, key) != value for key, value in data.items()):
                        row.review_status = 'draft'
                    for key, value in data.items():
                        setattr(row, key, value)
                    action = 'activity_table.update'
            session.flush()
            output['table'] = table_snapshot(row)
            return MutationChange('activity_table', table_id, action, before, output['table'])
        result = self.workspace_service.mutate(session, workspace_id=workspace_id, expected_version=version, actor=actor, mutation=mutation)
        return ({'deleted_table_id': table_id} if delete else output) | {'workspace_version': result.workspace.version}
