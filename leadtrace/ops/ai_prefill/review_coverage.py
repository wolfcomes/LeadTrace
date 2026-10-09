"""Known-candidate review coverage. This does not prove source completeness or accuracy."""
from pathlib import PurePosixPath
from app.ai_prefill.assistance_contracts import CandidateEnvelope
from app.ai_prefill.assistance_coverage import CompoundInventory


def review_targets(candidate: CandidateEnvelope, inventory: CompoundInventory) -> dict[str, list[str]]:
    payload = candidate.payload
    return {
        'source_identity': ['source'],
        'bibliography': ['paper'],
        'structures': [c.ref for c in payload.compounds],
        'locators': [c.ref for c in payload.structure_locators],
        'activities': [str(i) for i in range(len(payload.activities))],
        'edges': [e.ref for group in payload.lineages for e in group.edges],
        'groups': [g.ref for g in payload.lineages],
        'participation': [c.ref for c in payload.compounds],
        'evidence': [e.ref for e in payload.evidence],
        'edge_evidence_links': [str(i) for i in range(len(payload.edge_evidence_links))],
        'highlights': [h.ref for h in payload.compound_highlights],
        'inventory': [e.label for e in inventory.entries],
    }


def check_review_rows(targets: dict[str, list[str]], rows: list[dict]) -> dict:
    expected = {(domain, ref) for domain, refs in targets.items() for ref in refs}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Review row must be an object')
        domain, ref = row.get('domain'), row.get('ref')
        if not isinstance(domain, str) or not isinstance(ref, str) or (domain, ref) not in expected:
            raise ValueError('Unknown review domain/ref')
        if (domain, ref) in seen:
            raise ValueError('Duplicate review domain/ref')
        seen.add((domain, ref))
        if (not isinstance(row.get('source_locations'), list) or not row['source_locations']
                or not isinstance(row.get('checked_fields'), list) or not row['checked_fields']
                or not isinstance(row.get('field_results'), dict) or not row['field_results']
                or not isinstance(row.get('reason'), str) or not row['reason'].strip()
                or 'expected' not in row or 'observed' not in row
                or row.get('verdict') not in {'correct', 'incorrect', 'uncertain'}):
            raise ValueError('Incomplete item review evidence')
        if any(not isinstance(field, str) or not field or field not in row['field_results'] for field in row['checked_fields']):
            raise ValueError('Every checked field needs its result')
    return {'expected': len(expected), 'reviewed': len(seen),
            'missing': [{'domain': domain, 'ref': ref} for domain, ref in sorted(expected - seen)],
            'source_completeness_verified': False, 'scientific_approval': False}


def review_report_name(name: str) -> str:
    """Canonical name under outputs; accept the task-relative outputs/ spelling."""
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError('Unsafe review item report path')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or path.suffix != '.json':
        raise ValueError('Unsafe review item report path')
    if path.parts[0] == 'outputs':
        path = PurePosixPath(*path.parts[1:])
    return str(path)
