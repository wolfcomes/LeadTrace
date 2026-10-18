"""Read-only Reviewer diff: replay verified AI deltas into the human baseline.

First reverse the complete, validated history. Then replay only non-Reviewer
field deltas. Replaying whole rows would erase human edits on unrelated fields.
The resulting snapshot is a display baseline, never a persisted submission.
"""
from copy import deepcopy
from types import SimpleNamespace

from app.papers.metadata import ARTICLE_METADATA_DEFAULTS
from app.publications.comparison import (
    _FIELDS, _IncompleteHistory, _normalized, _reverse, _scientific_snapshot,
)
from app.workspaces.models import ChangeActorKind


def repair_event(event):
    kind = event.entity_type
    action = event.action.removeprefix(kind + '.repair_')
    if action not in {'create', 'update', 'delete', 'invalidate'}:
        raise _IncompleteHistory('Unsupported AI revision action')
    if event.actor_kind != ChangeActorKind.AI or event.actor_id is not None:
        raise _IncompleteHistory('AI revision actor mismatch')
    before, after = event.before_value, event.after_value
    if ((action == 'create' and (before is not None or after is None))
            or (action == 'delete' and (before is None or after is not None))
            or (action in {'update', 'invalidate'} and (before is None or after is None))):
        raise _IncompleteHistory('Incomplete AI revision delta')
    metadata = (after or before).get('_repair')
    if not isinstance(metadata, dict) or not metadata.get('repair_job_id'):
        raise _IncompleteHistory('Missing AI revision provenance')

    def row(value):
        if value is None:
            return None
        if value.get('_repair', metadata) != metadata or value.get('id') != str(event.entity_id):
            raise _IncompleteHistory('AI revision row identity mismatch')
        value = {k: v for k, v in value.items() if k != '_repair'}
        if kind in _FIELDS:
            return _normalized(kind, value)
        if kind == 'paper_section_review':
            if action != 'invalidate' or not {'section_key', 'state', 'note'}.issubset(value):
                raise _IncompleteHistory('Incomplete AI section invalidation')
            return {k: value[k] for k in ('section_key', 'state', 'note')}
        if kind == 'paper':
            if action != 'update':
                raise _IncompleteHistory('Unsupported AI bibliography action')
            # Repair serializes the DB row, whereas snapshots expose bibliography.
            fields = {'id', 'paper_key', 'title', 'journal', 'publication_year',
                      'volume', 'issue', 'doi', 'catalog_state', *ARTICLE_METADATA_DEFAULTS}
            if not fields.issubset(value):
                raise _IncompleteHistory('Incomplete AI bibliography row')
            return {k: value[k] for k in fields}
        raise _IncompleteHistory('Unsupported AI revision entity')

    return SimpleNamespace(entity_type=kind, entity_id=event.entity_id,
        action=('section.update' if kind == 'paper_section_review' else
                'bibliography.update' if kind == 'paper' else
                f'{kind}.{"update" if action == "invalidate" else action}'),
        before_value=row(before), after_value=row(after))


def _apply_delta(target, before, after):
    """Apply only changed dictionary paths, retaining other human baseline values."""
    for key in before.keys() | after.keys():
        if key not in after:
            target.pop(key, None)
        elif key not in before:
            target[key] = deepcopy(after[key])
        elif before[key] != after[key]:
            if isinstance(before[key], dict) and isinstance(after[key], dict):
                if key not in target:
                    target[key] = {}
                if not isinstance(target[key], dict):
                    raise _IncompleteHistory('Overlapping AI and Reviewer metadata types')
                _apply_delta(target[key], before[key], after[key])
            elif isinstance(before[key], list) and isinstance(after[key], list) and target.get(key) != before[key]:
                raise _IncompleteHistory('AI and Reviewer edits overlap an ordered metadata list')
            else:
                target[key] = deepcopy(after[key])


def _replay_delta(target, before, after):
    _apply_delta(target.setdefault('paper', {}), before.get('paper', {}), after.get('paper', {}))
    for collection in {'sections', *(v[0] for v in _FIELDS.values())}:
        key = 'section_key' if collection == 'sections' else 'id'
        old = {r[key]: r for r in before.get(collection, [])}
        new = {r[key]: r for r in after.get(collection, [])}
        rows = target.setdefault(collection, [])
        for identity in old.keys() | new.keys():
            found = next((r for r in rows if r[key] == identity), None)
            if identity not in new:
                if found is not None:
                    rows.remove(found)
            elif identity not in old:
                if found is not None:
                    rows.remove(found)
                rows.append(deepcopy(new[identity]))
            elif found is not None:
                _apply_delta(found, old[identity], new[identity])
            # An AI update to a human-created row must not turn its creation
            # into an AI addition. Keep it absent from the human baseline.


def reviewer_only_baseline(snapshot, events, *, verified_repair_ids=(), expected_start=None):
    baseline = deepcopy(snapshot)
    deltas = []
    try:
        for event in reversed(events):
            current = deepcopy(baseline)
            normalized = event
            if '.repair_' in event.action:
                if event.id not in verified_repair_ids:
                    raise _IncompleteHistory('Unverified AI revision delivery')
                normalized = repair_event(event)
                # Ordinary human compound/lineage deletes contain cascade
                # bundles. Repairs log every deleted row individually.
                if normalized.entity_type in _FIELDS and normalized.action.endswith('.delete'):
                    from app.publications.comparison import _reverse_row
                    _reverse_row(baseline, normalized.entity_type, normalized.before_value,
                                 normalized.after_value, str(normalized.entity_id))
                else:
                    _reverse_with_completion(baseline, normalized, snapshot)
            else:
                _reverse_with_completion(baseline, normalized, snapshot)
            if event.actor_kind != ChangeActorKind.REVIEWER:
                deltas.append((deepcopy(baseline), current))
        if expected_start is not None:
            actual = _scientific_snapshot(baseline)
            expected = _scientific_snapshot(expected_start)
            # Submission derives completed sections from viewing receipts; the
            # editable row can still be pending at the next round's start.
            complete = {r.get('section_key') for r in expected_start.get('review_progress', {}).get('sections', []) if r.get('complete') is True}
            for row in expected['sections']:
                other = next((r for r in actual['sections'] if r['section_key'] == row['section_key']), None)
                if (other and row['section_key'] in complete and row['state'] == 'completed'
                        and other['state'] == 'pending' and row['note'] == other['note']):
                    row['state'] = 'pending'
            if actual != expected:
                raise _IncompleteHistory('Reconstructed history disagrees with previous Reviewer submission')
        for before, after in reversed(deltas):
            _replay_delta(baseline, before, after)
    except (KeyError, TypeError, AttributeError, _IncompleteHistory) as error:
        return None, [f'Reviewer-only comparison unavailable: {error}. Inspect recorded changes and the complete frozen submission.']
    return baseline, []


def _reverse_with_completion(baseline, event, frozen):
    if event.entity_type == 'paper_section_review' and event.action == 'section.update':
        after = event.after_value
        complete = {r.get('section_key') for r in frozen.get('review_progress', {}).get('sections', []) if r.get('complete') is True}
        for row in baseline.get('sections', []):
            if (row['section_key'] == after['section_key'] and row['section_key'] in complete
                    and row['state'] == 'completed' and after['state'] == 'pending'
                    and row['note'] == after['note']):
                row['state'] = 'pending'
    _reverse(baseline, event)


def verified_repairs(session, events, source):
    """Bind repair attribution to an applied task for this exact workspace/source."""
    from uuid import UUID
    from app.ai_tasks.models import AiTask
    repairs = [e for e in events if '.repair_' in e.action]
    jobs = {}
    valid = set()
    for event in repairs:
        try:
            metadata = (event.after_value or event.before_value)['_repair']
            job_id = UUID(metadata['repair_job_id'])
            if job_id not in jobs:
                jobs[job_id] = session.get(AiTask, job_id)
            job = jobs[job_id]
            if (not job or job.delivery_state != 'applied'
                    or job.paper_id != event.paper_id or job.workspace_id != event.workspace_id
                    or job.source_sha256 != source['sha256']
                    or job.result_summary.get('applied_workspace_version', 0) <= job.workspace_version):
                continue
            if metadata.get('delivery_mode') == 'automatic_revision':
                if job.action != 'revise' or metadata.get('requested_by_id') != str(job.requested_by_id):
                    continue
            elif (job.action not in {'repair', 'review'}
                    or metadata.get('accepted_by_id') != job.result_summary.get('accepted_by')):
                continue
            repair_event(event)
            valid.add(event.id)
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    return valid
