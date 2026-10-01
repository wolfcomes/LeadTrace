"""Compound/Lineage viewing progress, separate from scientific approval."""
from collections import defaultdict
from uuid import UUID
from sqlalchemy import select
from app.workspaces.models import WorkspaceViewReceipt
from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash

VIEW_KINDS = ('compound', 'lineage')
SECTION_VIEW_GROUP = {
    'compounds': 'compounds', 'structures': 'compounds', 'activities': 'compounds',
    'lineages': 'lineages', 'edge_evidence': 'lineages',
}


def review_items(snapshot):
    items = []
    source = snapshot['source']['sha256']
    structures = {r['compound_id']: r for r in snapshot['structures']}
    evidence = {r['id']: r for r in snapshot['evidence']}
    images, activities, members, edges, links = (defaultdict(list) for _ in range(5))
    for row in snapshot['structure_source_images']:
        images[row['compound_id']].append(row)
    for row in snapshot['activities']:
        activities[row['compound_id']].append([row, evidence.get(row.get('evidence_id'))])
    for row in snapshot['lineage_members']:
        members[row['lineage_id']].append(row)
    for row in snapshot['lineage_edges']:
        edges[row['lineage_id']].append(row)
    for row in snapshot['edge_evidence_links']:
        links[row['edge_id']].append([row, evidence.get(row['evidence_id'])])

    def add(kind, entity_id, section, label, content):
        signature = canonical_snapshot_hash({
            'view_scope': 'compound-lineage-v2', 'source': source, 'content': content,
        })
        items.append({'kind': kind, 'entity_id': entity_id, 'section_key': section,
                      'label': label, 'signature': signature})
        return signature

    highlights = defaultdict(list)
    for row in snapshot.get('compound_highlights', []):
        highlights[row['compound_id']].append([row, evidence.get(row['evidence_id'])])
    compound_signatures = {}
    for row in snapshot['compounds']:
        cid = row['id']
        compound_signatures[cid] = add('compound', cid, 'compounds', row['compound_label'],
            [row, structures.get(cid), images[cid], activities[cid]] + ([highlights[cid]] if highlights[cid] else []))
    for row in snapshot['lineages']:
        lid = row['id']
        add('lineage', lid, 'lineages', row['lineage_label'], [
            row, members[lid], [compound_signatures.get(x['compound_id']) for x in members[lid]],
            [[edge, links[edge['id']]] for edge in edges[lid]],
        ])
    return items


def get_progress(session, workspace_id: UUID, reviewer_id: UUID):
    snapshot = build_paper_snapshot(session, workspace_id)
    # Historical fine-grained receipts are retained but do not become group approvals.
    receipts = {(x.kind, str(x.entity_id)): x for x in session.scalars(select(WorkspaceViewReceipt).where(
        WorkspaceViewReceipt.workspace_id == workspace_id,
        WorkspaceViewReceipt.reviewer_id == reviewer_id,
        WorkspaceViewReceipt.kind.in_(VIEW_KINDS),
    ))}
    items = review_items(snapshot)
    for item in items:
        receipt = receipts.get((item['kind'], item['entity_id']))
        item['viewed'] = bool(receipt and receipt.viewed_at and receipt.signature == item['signature'])
    sections = []
    for section in snapshot['sections']:
        if section['section_key'] not in ('compounds', 'lineages'):
            continue
        rows = [x for x in items if x['section_key'] == section['section_key']]
        seen = sum(x['viewed'] for x in rows)
        sections.append({'section_key': section['section_key'], 'total': len(rows), 'viewed': seen,
                         'complete': bool(rows) and seen == len(rows), 'state': section['state'], 'note': section['note']})
    return {'workspace_id': str(workspace_id), 'workspace_version': snapshot['workspace_version'],
            'items': items, 'sections': sections, 'tracking_started': bool(receipts)}
