"""Reversible reviewer edits; immutable audit history is never rewritten."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy import Numeric

from app.activity_tables.models import ActivityTable
from app.activities.models import Activity
from app.compounds.models import Compound, CompoundHighlight
from app.evidence.models import Evidence, EdgeEvidenceLink
from app.lineages.models import Lineage, LineageMember, LineageEdge, LineagePresentation
from app.papers.metadata import ARTICLE_METADATA_FIELDS
from app.structures.models import Structure
from app.structure_images.models import StructureSourceImage
from app.workspaces.models import (PaperSectionReview, WorkspaceEdit, WorkspaceEditCursor,
    WorkspaceViewReceipt, ChangeEvent, ChangeActorKind)

# Parent-first dependency order, reversed for deletes. Assets and job records are
# deliberately not restored: the immutable referenced assets remain authoritative.
MODELS = (Compound, Evidence, Lineage, Structure, StructureSourceImage, LineageMember,
          LineageEdge, EdgeEvidenceLink, Activity, ActivityTable, CompoundHighlight, PaperSectionReview)
PAPER_FIELDS = ('title', 'journal', 'publication_year', 'volume', 'issue', 'doi', *ARTICLE_METADATA_FIELDS)

def value(v):
    if isinstance(v, Decimal): return format(v.normalize(), 'f')
    if isinstance(v, (UUID, datetime)): return str(v)
    if isinstance(v, Enum): return v.value
    if isinstance(v, dict): return {k:value(x) for k,x in v.items()}
    if isinstance(v, (tuple,list)): return [value(x) for x in v]
    return v

def row_value(row):
    return {col.name:value(getattr(row,col.name)) for col in row.__table__.columns
            if col.name not in ('created_at','updated_at')}

def capture(session, context):
    session.flush()
    result = {'paper':{key:value(getattr(context.paper,key)) for key in PAPER_FIELDS}}
    for model in MODELS:
        result[model.__tablename__] = [row_value(row) for row in session.scalars(
            select(model).where(model.workspace_id == context.workspace.id).order_by(model.id))]
    # Layouts are auxiliary: save them for parent deletion recovery, but layout
    # saves have their own revision and must not invalidate scientific undo.
    result['lineage_presentations'] = [row_value(row) for row in session.scalars(
        select(LineagePresentation).where(LineagePresentation.workspace_id == context.workspace.id)
        .order_by(LineagePresentation.id))]
    return deepcopy(result)

def record(session, context, actor_id, action, before, after, previous_version):
    cursor = session.get(WorkspaceEditCursor, context.workspace.id)
    if cursor is None:
        cursor = WorkspaceEditCursor(workspace_id=context.workspace.id, reviewer_id=actor_id,
            expected_version=previous_version, undo_ids=[], redo_ids=[])
        session.add(cursor)
    if cursor.expected_version != previous_version or cursor.reviewer_id != actor_id:
        cursor.undo_ids = []
    entry = WorkspaceEdit(workspace_id=context.workspace.id, reviewer_id=actor_id,
        action=action, before_state=before, after_state=after)
    session.add(entry); session.flush()
    cursor.undo_ids = [*cursor.undo_ids, str(entry.id)]
    cursor.redo_ids = []
    cursor.reviewer_id = actor_id
    cursor.expected_version = context.workspace.version
    session.flush()

def _convert(model, data):
    result={}
    for column in model.__table__.columns:
        if column.name not in data: continue
        item=deepcopy(data[column.name])
        if item is not None and isinstance(column.type,PGUUID): item=UUID(item)
        if item is not None and isinstance(column.type,Numeric): item=Decimal(item)
        result[column.name]=item
    return result

def restore(session, context, current, target):
    from app.workspaces.review_progress import review_items
    from app.workspaces.snapshot import build_paper_snapshot
    # Pre-migration edit snapshots have no table collection; all established
    # collections remain required so incomplete history cannot erase records.
    target = dict(target, activity_tables=target.get('activity_tables', []))
    old_signatures={(r['kind'],r['entity_id']):r['signature']
                    for r in review_items(build_paper_snapshot(session,context.workspace.id))}
    # Apply only changed rows. Keeping unaffected records avoids resetting crop
    # jobs, immutable assets, provenance, or presentation state.
    for model in reversed(MODELS):
        key=model.__tablename__
        desired={r['id'] for r in target[key]}
        removed=[UUID(r['id']) for r in current[key] if r['id'] not in desired]
        if removed:
            session.execute(delete(model).where(model.workspace_id==context.workspace.id,model.id.in_(removed)),
                            execution_options={'synchronize_session':'fetch'})
    session.flush()
    for model in MODELS:
        key=model.__tablename__
        existing={r['id']:r for r in current[key]}
        for data in target[key]:
            if existing.get(data['id']) == data: continue
            converted=_convert(model,data)
            row=session.get(model,converted['id'])
            if row is None: session.add(model(**converted))
            else:
                for name,item in converted.items(): setattr(row,name,item)
        session.flush()
    restored_lineages = {row['id'] for row in target['lineages']} - {row['id'] for row in current['lineages']}
    for data in target.get('lineage_presentations', []):
        if data['lineage_id'] not in restored_lineages:
            continue
        converted = _convert(LineagePresentation, data)
        # A stale layout tab must never match the pre-deletion revision.
        converted['revision'] += 1
        session.add(LineagePresentation(**converted))
    for key,item in target['paper'].items(): setattr(context.paper,key,deepcopy(item))
    # A restored signature must not resurrect an old viewed receipt. Clear only
    # the affected groups (including Lineages depending on changed Compounds).
    from app.workspaces.review_progress import review_items
    from app.workspaces.snapshot import build_paper_snapshot
    session.flush()
    snapshot=build_paper_snapshot(session,context.workspace.id)
    signatures={(r['kind'],r['entity_id']):r['signature'] for r in review_items(snapshot)}
    for receipt in session.scalars(select(WorkspaceViewReceipt).where(WorkspaceViewReceipt.workspace_id==context.workspace.id)):
        key=(receipt.kind,str(receipt.entity_id))
        if signatures.get(key) != old_signatures.get(key):
            receipt.viewed_at=None
    session.flush()

def status(session, context, actor_id):
    cursor=session.get(WorkspaceEditCursor,context.workspace.id)
    valid=bool(cursor and cursor.expected_version==context.workspace.version and cursor.reviewer_id==actor_id
               and context.workspace.state.value=='editing')
    def action(ids):
        entry=session.get(WorkspaceEdit,UUID(ids[-1])) if ids else None
        return entry.action if entry else None
    return {'workspace_version':context.workspace.version,
            'undo_action':action(cursor.undo_ids) if valid else None,
            'redo_action':action(cursor.redo_ids) if valid else None}

def move(session,context,actor_id,direction):
    from app.api.errors import APIError
    cursor=session.get(WorkspaceEditCursor,context.workspace.id)
    if not cursor or cursor.expected_version!=context.workspace.version or cursor.reviewer_id!=actor_id:
        raise APIError(409,'EDIT_HISTORY_CHANGED','History no longer matches the current workspace')
    source=cursor.undo_ids if direction=='undo' else cursor.redo_ids
    if not source: raise APIError(409,'EDIT_HISTORY_EMPTY','No edit is available')
    entry=session.get(WorkspaceEdit,UUID(source[-1]))
    if not entry or entry.workspace_id!=context.workspace.id or entry.reviewer_id!=actor_id:
        raise APIError(409,'EDIT_HISTORY_CHANGED','History is unavailable')
    current=capture(session,context)
    expected=entry.after_state if direction=='undo' else entry.before_state
    target=entry.before_state if direction=='undo' else entry.after_state
    def scientific(state):
        return {key: item for key, item in state.items() if key != 'lineage_presentations'
                and not (key == 'activity_tables' and not item)}
    if scientific(current)!=scientific(expected):
        raise APIError(409,'EDIT_HISTORY_CHANGED','Content changed since this edit')
    target = deepcopy(target)
    restored_lineages = {row['id'] for row in target['lineages']} - {row['id'] for row in current['lineages']}
    if restored_lineages:
        # Repeated undo/redo may delete a parent after its layout was edited.
        # Recover the most recent pre-deletion layouts, not the original edit's
        # older coordinates. Compensation events are immutable and versioned.
        events = list(session.scalars(select(ChangeEvent).where(
            ChangeEvent.workspace_id == context.workspace.id,
            ChangeEvent.entity_type == 'workspace_edit', ChangeEvent.entity_id == entry.id,
            ChangeEvent.action.in_(['workspace.undo', 'workspace.redo']))))
        events.sort(key=lambda event: (event.after_value or {}).get('snapshot', {}).get('workspace_version', 0), reverse=True)
        unresolved = set(restored_lineages)
        for event in events:
            before, after = event.before_value or {}, event.after_value or {}
            if 'lineage_presentations' not in before:
                continue
            before_ids = {row['id'] for row in before.get('snapshot', {}).get('lineages', [])}
            after_ids = {row['id'] for row in after.get('snapshot', {}).get('lineages', [])}
            deleted = unresolved & (before_ids - after_ids)
            if not deleted:
                continue
            target['lineage_presentations'] = [row for row in target.get('lineage_presentations', [])
                if row['lineage_id'] not in deleted] + [row for row in before['lineage_presentations']
                if row['lineage_id'] in deleted]
            unresolved -= deleted
            if not unresolved:
                break
    from app.workspaces.snapshot import build_paper_snapshot
    before_snapshot=build_paper_snapshot(session,context.workspace.id)
    restore(session,context,current,target)
    context.workspace.version+=1
    if direction=='undo':
        cursor.undo_ids=source[:-1];cursor.redo_ids=[*cursor.redo_ids,str(entry.id)]
    else:
        cursor.redo_ids=source[:-1];cursor.undo_ids=[*cursor.undo_ids,str(entry.id)]
    cursor.expected_version=context.workspace.version
    after_snapshot=build_paper_snapshot(session,context.workspace.id)
    session.add(ChangeEvent(paper_id=context.paper.id,workspace_id=context.workspace.id,
        entity_type='workspace_edit',entity_id=entry.id,action='workspace.'+direction,
        before_value={'snapshot':before_snapshot, 'lineage_presentations':current.get('lineage_presentations', [])},
        after_value={'snapshot':after_snapshot},
        actor_kind=ChangeActorKind.REVIEWER,actor_id=actor_id))
    session.flush()
    return status(session,context,actor_id)
