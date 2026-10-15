"""Read-only, conservative reconstruction of a review round's scientific baseline.

Frozen submissions remain the authority. Historical row events use a different
shape from snapshots; normalize only known shapes and require the reverse chain
to agree with the frozen state. Unsupported history produces no baseline, never
an apparently empty comparison. This is a display projection, not a saved version.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from app.workspaces.models import ChangeActorKind, ChangeEvent

_COMMON = 'id paper_id workspace_id '
_FIELDS = {
    'compound': ('compounds', _COMMON + 'compound_label display_name description sort_order created_by_kind'),
    'structure': ('structures', _COMMON + 'compound_id smiles canonical_smiles molfile inchi inchikey depiction_asset_id status input_method'),
    'structure_source_image': ('structure_source_images', _COMMON + 'compound_id source_sha256 page_number x0 y0 x1 y1 source_context label reviewer_note crop_status crop_asset_id'),
    'lineage': ('lineages', _COMMON + 'lineage_label description sort_order'),
    'lineage_member': ('lineage_members', _COMMON + 'lineage_id compound_id role sort_order'),
    'lineage_edge': ('lineage_edges', _COMMON + 'lineage_id parent_compound_id child_compound_id relation_type modification_summary review_status sort_order'),
    'evidence': ('evidence', _COMMON + 'kind source_sha256 page_number x0 y0 x1 y1 quoted_text caption crop_asset_id reviewer_note'),
    'edge_evidence_link': ('edge_evidence_links', _COMMON + 'edge_id evidence_id role'),
    'activity': ('activities', _COMMON + 'compound_id evidence_id assay_name metric operator value unit context sort_order'),
    'compound_highlight': ('compound_highlights', _COMMON + 'compound_id evidence_id role scope rationale review_hint review_status created_by_kind'),
}
_OPTIONAL = {'compound': ('review_hint',), 'activity': ('review_hint',),
             'lineage_edge': ('review_hint',), 'lineage': ('lineage_type',)}
_NUMERIC = {'x0', 'y0', 'x1', 'y1', 'value'}
# These mutate workflow, not scientific content. Sections are deliberately NOT
# skipped: not_reported and clearing a section note must remain reviewable.
_WORKFLOW = {'workspace.submit', 'paper.review_assigned', 'submission.request_changes',
             'submission.approve', 'submission.approve_with_unresolved', 'assignment.recall',
             'workspace.metadata_revision_started'}


class _IncompleteHistory(ValueError):
    pass


def _normalized(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _IncompleteHistory('Invalid historical row')
    row = deepcopy(value)
    if kind in {'evidence', 'structure_source_image'} and 'bbox' in row:
        bbox = row.pop('bbox')
        if bbox is not None and (not isinstance(bbox, dict) or set(bbox) != {'x0', 'y0', 'x1', 'y1'}):
            raise _IncompleteHistory('Incomplete historical coordinates')
        row.update({key: str(bbox[key]) if bbox else None for key in ('x0', 'y0', 'x1', 'y1')})
    required = _FIELDS[kind][1].split()
    if not set(required).issubset(row):
        raise _IncompleteHistory(f'Incomplete historical {kind} row')
    allowed = set(required) | set(_OPTIONAL.get(kind, ())) | {'created_by_kind'}
    if set(row) - allowed:
        raise _IncompleteHistory(f'Unsupported historical {kind} fields')
    result = {key: row[key] for key in required}
    for key in _OPTIONAL.get(kind, ()):
        if row.get(key) and not (key == 'lineage_type' and row[key] == 'unspecified'):
            result[key] = row[key]
    return result


def _equal(left: dict, right: dict) -> bool:
    if set(left) != set(right):
        return False
    for key, value in left.items():
        other = right[key]
        if key in _NUMERIC and value is not None and other is not None:
            try:
                if Decimal(str(value)) == Decimal(str(other)):
                    continue
            except InvalidOperation:
                return False
        if value != other:
            return False
    return True


def _reverse_row(snapshot: dict, kind: str, before: dict | None,
                 after: dict | None, entity_id: str) -> None:
    collection = _FIELDS[kind][0]
    rows = snapshot.setdefault(collection, [])
    if not isinstance(rows, list):
        raise _IncompleteHistory('Invalid frozen collection')
    found = [row for row in rows if row.get('id') == entity_id]
    if len(found) > 1:
        raise _IncompleteHistory('Duplicate historical row identity')
    normalized_before = _normalized(kind, before) if before is not None else None
    normalized_after = _normalized(kind, after) if after is not None else None
    for row in (normalized_before, normalized_after):
        if row is not None and row['id'] != entity_id:
            raise _IncompleteHistory('Historical row identity mismatch')
    if normalized_after is None:
        if found or normalized_before is None:
            raise _IncompleteHistory('Historical deletion disagrees with frozen content')
    elif not found or not _equal(_normalized(kind, found[0]), normalized_after):
        raise _IncompleteHistory('Historical after-value disagrees with frozen content')
    if found:
        rows.remove(found[0])
    if normalized_before is not None:
        rows.append(normalized_before)


def _restore_bundle(snapshot: dict, event: ChangeEvent) -> bool:
    """Only deletion bundles that explicitly inventory every cascade are safe."""
    bundles = {
        'compound.delete': ('compound', {'compound', 'structure', 'structure_source_images'},
                            [('compound', 'compound', False), ('structure', 'structure', False),
                             ('structure_source_images', 'structure_source_image', True)]),
        'lineage.delete': ('lineage', {'lineage', 'members', 'edges', 'evidence_links'},
                           [('lineage', 'lineage', False), ('members', 'lineage_member', True),
                            ('edges', 'lineage_edge', True), ('evidence_links', 'edge_evidence_link', True)]),
        'lineage_edge.delete': ('edge', {'edge', 'evidence_links'},
                               [('edge', 'lineage_edge', False), ('evidence_links', 'edge_evidence_link', True)]),
    }
    if event.action not in bundles:
        return False
    root, keys, parts = bundles[event.action]
    before = event.before_value
    if not isinstance(before, dict) or set(before) != keys or event.after_value is not None:
        raise _IncompleteHistory('Incomplete historical deletion cascade')
    if not isinstance(before[root], dict) or before[root].get('id') != str(event.entity_id):
        raise _IncompleteHistory('Historical deletion identity mismatch')
    for key, kind, many in parts:
        value = before[key]
        if many and not isinstance(value, list):
            raise _IncompleteHistory('Incomplete historical deletion cascade')
        for row in value if many else ([value] if value is not None else []):
            _reverse_row(snapshot, kind, row, None, row.get('id'))
    return True


def _reverse(snapshot: dict, event: ChangeEvent) -> None:
    if event.action in _WORKFLOW:
        return
    if _restore_bundle(snapshot, event):
        return
    before, after = event.before_value, event.after_value
    if event.entity_type == 'paper' and event.action in {'bibliography.update', 'paper.update', 'bibliography.ai_supplement'}:
        if not isinstance(before, dict) or not isinstance(after, dict) or set(before) != set(after):
            raise _IncompleteHistory('Incomplete historical bibliography')
        paper = snapshot.get('paper', {})
        from app.papers.metadata import ARTICLE_METADATA_DEFAULTS
        if any(paper.get(key, ARTICLE_METADATA_DEFAULTS.get(key)) != value for key, value in after.items()):
            raise _IncompleteHistory('Bibliography history disagrees with frozen content')
        paper.update(deepcopy(before))
        for key, default in ARTICLE_METADATA_DEFAULTS.items():
            if key in paper and paper[key] == default:
                paper.pop(key)
        return
    if event.action == 'section.update' and event.entity_type == 'paper_section_review':
        if not isinstance(before, dict) or not isinstance(after, dict) or set(before) != {'section_key', 'state', 'note'} or set(after) != set(before):
            raise _IncompleteHistory('Incomplete historical section')
        matches = [row for row in snapshot.get('sections', []) if row.get('section_key') == after['section_key']]
        if len(matches) != 1 or matches[0] != after or before['section_key'] != after['section_key']:
            raise _IncompleteHistory('Section history disagrees with frozen content')
        matches[0].update(deepcopy(before))
        return
    if event.entity_type not in _FIELDS or event.action not in {
        f'{event.entity_type}.create', f'{event.entity_type}.update',
        f'{event.entity_type}.delete', 'structure_source_image.retry',
    }:
        # Reorder events record IDs, not prior numerical sort_order values.
        # New scientific event types must be supported explicitly before use.
        raise _IncompleteHistory(f'Unsupported historical action: {event.action}')
    _reverse_row(snapshot, event.entity_type, before, after, str(event.entity_id))


def reconstruct_reviewer_baseline(snapshot: dict[str, Any], events: Sequence[ChangeEvent]
                                  ) -> tuple[dict[str, Any] | None, list[str]]:
    first = next((index for index, event in enumerate(events)
                  if event.actor_kind == ChangeActorKind.REVIEWER and event.action != 'workspace.submit'), None)
    if first is None:
        return None, ['No recorded Reviewer starting boundary; absence of history does not prove absence of changes.']
    if snapshot.get('schema_version') != 1:
        return None, ['Unsupported frozen snapshot version; the Reviewer starting state cannot be reconstructed.']
    baseline = deepcopy(snapshot)
    try:
        for event in reversed(events[first:]):
            _reverse(baseline, event)
    except (KeyError, TypeError, AttributeError, _IncompleteHistory) as error:
        return None, [f'Reviewer starting state unavailable: {error}. Inspect recorded changes and the complete frozen submission.']
    return baseline, []
