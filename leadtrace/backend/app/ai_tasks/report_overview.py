"""Concise, conservative statistics derived from frozen candidate/review artifacts.

These are AI assessment counts, never scientific approval or population accuracy.
Detailed item records stay in the task bundle for repair and audit.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from pathlib import Path
import re

from app.ai_prefill.assistance_contracts import CandidateEnvelope
from app.ai_prefill.assistance_coverage import CompoundInventory, check_compound_coverage
from app.ai_prefill.occurrences import occurrence_groups
from app.ai_tasks.producer_report import read_artifact
from leadtrace.ops.ai_prefill.review_coverage import check_review_rows, review_targets


# Explicit field names are intentionally conservative. Free prose, a top-level
# "correct", or just a numeric value check does not establish a whole-row result.
_FIELDS = {
    'structures': [
        {'connectivity', 'atom_connectivity', 'ring_connectivity'},
        {'regiochemistry', 'substitution', 'substitution_positions', 'anchors'},
        {'stereochemistry', 'stereo'}, {'chemical_form', 'form', 'salt_form'},
    ],
    'activities': [
        {'compound', 'compound_identity', 'compound_ref'},
        {'assay', 'assay_name', 'target_assay'}, {'metric', 'endpoint'},
        {'value'}, {'unit'}, {'operator'}, {'conditions', 'context'},
        {'source', 'source_identity', 'evidence_ref', 'source_attribution'},
    ],
    'edges': [
        {'type', 'relation_type'}, {'endpoints', 'endpoint_identity', 'endpoint_identities'},
        {'direction'}, {'basis', 'rationale', 'evidence', 'scientific_basis'},
    ],
    'groups': [
        {'type', 'lineage_type'}, {'scope', 'group_scope'},
        {'components', 'connectivity', 'grouping'}, {'roles', 'member_roles'},
    ],
    'locators': [
        {'identity', 'compound_identity', 'complete_identity'},
        {'bbox', 'crop', 'crop_content'}, {'source', 'page', 'source_location'},
    ],
    'evidence': [
        {'source', 'source_identity', 'source_location'},
        {'content', 'quote', 'quoted_text', 'caption'},
    ],
    'edge_evidence_links': [
        {'identity', 'evidence_identity', 'link_identity'}, {'role', 'support'},
    ],
}


def _targets(candidate, inventory):
    if inventory is not None:
        return review_targets(candidate, inventory)
    # Inventory coverage is unknown; candidate-domain audit coverage can still
    # have an honest denominator. Do not invent inventory identities from labels.
    class EmptyInventory:
        entries = ()
    return review_targets(candidate, EmptyInventory())


def _valid_inventory(candidate, inventory):
    if inventory is None:
        return None, None
    try:
        if not isinstance(inventory, CompoundInventory):
            inventory = CompoundInventory.model_validate(inventory)
        return inventory, check_compound_coverage(candidate, inventory)
    except (ValueError, TypeError):
        return None, None


def _percent(checked, expected):
    return round(100 * checked / expected, 1) if expected else None


def _result(value):
    if isinstance(value, dict):
        value = value.get('verdict')
    return value if isinstance(value, str) and value in {'correct', 'incorrect', 'uncertain'} else 'uncertain'


def _row_state(row, *, synthesis=False, evidence_crop=False):
    if row is None:
        return 'unreviewed'
    results = row['field_results']
    # A contradictory extra field is still a known problem, even when omitted
    # from checked_fields or hidden behind a top-level "correct" conclusion.
    outcomes = [_result(value) for value in results.values()]
    if row['verdict'] == 'incorrect' or 'incorrect' in outcomes:
        return 'incorrect'
    if row['verdict'] != 'correct' or any(value != 'correct' for value in outcomes):
        return 'uncertain'
    checked = {field.strip().casefold() for field in row['checked_fields']}
    requirements = list(_FIELDS.get(row['domain'], []))
    if synthesis:
        requirements.append({'steps', 'reaction_steps', 'transformation', 'conditions'})
    if evidence_crop:
        requirements.append({'bbox', 'crop', 'crop_content'})
    if not requirements or any(not checked.intersection(aliases) for aliases in requirements):
        return 'uncertain'
    return 'supported'


def actionable_review_rows(candidate: CandidateEnvelope, rows: list[dict]) -> list[dict]:
    """Select actionable, normalized findings from already validated item rows.

    The report/repair caller must use read_review_rows first for frozen identity
    and schema validation. Keep source evidence intact, including the original
    conclusion when explicit field results or incomplete scope contradict it.
    Unmapped domains do not acquire invented mandatory field requirements.
    """
    synthesis_edges = {edge.ref for group in candidate.payload.lineages
                       if group.lineage_type == 'synthesis' for edge in group.edges}
    cropped_evidence = {item.ref for item in candidate.payload.evidence if item.bbox is not None}
    findings = []
    for row in rows:
        verdict = row['verdict']
        field_verdicts = [value.get('verdict') if isinstance(value, dict) else value
                          for value in row['field_results'].values()]
        explanation = None
        if verdict != 'incorrect' and 'incorrect' in field_verdicts:
            verdict = 'incorrect'
            explanation = 'An explicit field result reports an error despite the overall verdict.'
        elif verdict == 'correct':
            if row['domain'] in _FIELDS:
                assessed = _row_state(row,
                    synthesis=row['domain'] == 'edges' and row['ref'] in synthesis_edges,
                    evidence_crop=row['domain'] == 'evidence' and row['ref'] in cropped_evidence)
                if assessed != 'supported':
                    verdict = assessed
                    explanation = 'Core-field checks are incomplete or unresolved; the overall correct verdict is not supported.'
            elif 'uncertain' in field_verdicts:
                verdict = 'uncertain'
                explanation = 'An explicit field result remains uncertain despite the overall verdict.'
        if verdict == 'correct':
            continue
        normalized = dict(row)
        if verdict != row['verdict']:
            normalized.update(original_verdict=row['verdict'], original_reason=row['reason'],
                              verdict=verdict, reason=f"{explanation} Original reason: {row['reason']}")
        findings.append(normalized)
    return findings


def _dependent(state, dependencies):
    # A missing row remains unreviewed. A checked row cannot silently ignore
    # a proven error in the scientific identity on which it depends.
    if state == 'unreviewed' or state == 'incorrect':
        return state
    if 'incorrect' in dependencies:
        return 'incorrect'
    if any(item != 'supported' for item in dependencies):
        return 'uncertain'
    return state


def _group_state(states):
    if 'incorrect' in states:
        return 'incorrect'
    if all(state == 'unreviewed' for state in states):
        return 'unreviewed'
    if all(state == 'supported' for state in states):
        return 'supported'
    return 'uncertain'


def _region(item):
    return (item.page_number, *(getattr(item.bbox, key).quantize(
        Decimal('0.0000000001'), rounding=ROUND_HALF_UP) for key in ('x0', 'y0', 'x1', 'y1')))


def read_review_rows(directory: Path, candidate_raw: bytes) -> list[dict]:
    """Load bound item reports safely; reject invalid records instead of counting.

    Callers must separately bind candidate_raw to their frozen task/workspace.
    This binds the review summary and inventory to those exact candidate bytes.
    """
    directory = Path(directory)
    candidate = CandidateEnvelope.model_validate_json(candidate_raw)
    summary_raw = read_artifact(directory, 'outputs/audit-summary.json')
    summary = json.loads(summary_raw)
    if (not isinstance(summary, dict)
            or summary.get('candidate_file_sha256') != sha256(candidate_raw).hexdigest()
            or summary.get('source_sha256') != candidate.source.source_sha256
            or summary.get('scientific_approval') is not False):
        raise ValueError('Review summary is not bound to this candidate/source')
    inventory = CompoundInventory.model_validate_json(read_artifact(directory, 'inputs/compound-inventory.json'))
    check_compound_coverage(candidate, inventory)
    names = summary.get('item_reports')
    if not isinstance(names, list) or len(names) > 1000:
        raise ValueError('Review item report list missing or oversized')
    rows = []
    byte_count = len(summary_raw)
    for name in names:
        from leadtrace.ops.ai_prefill.review_coverage import review_report_name
        # Both outputs/foo.json and foo.json identify the same output artifact.
        raw = read_artifact(directory / 'outputs', review_report_name(name))
        byte_count += len(raw)
        if byte_count > 32 * 1024 * 1024:
            raise ValueError('Review item reports exceed the total size limit')
        items = json.loads(raw)
        if not isinstance(items, list):
            raise ValueError('Review item report must contain a list')
        rows.extend(items)
        if len(rows) > 20000:
            raise ValueError('Review item reports exceed the row limit')
    check_review_rows(review_targets(candidate, inventory), rows)
    return rows


def build_overview(candidate: CandidateEnvelope, *, producer_report=None, review_rows=None, inventory=None) -> dict:
    """Summarize candidate totals and explicit review scope without item dumps.

    The caller owns artifact/workspace hash binding. Supplying review_rows,
    including an empty list, selects independent review. Invalid, duplicate, or
    foreign rows are errors. Production self-check claims are never confidence.
    """
    inventory, coverage = _valid_inventory(candidate, inventory)
    independent = review_rows is not None
    targets = _targets(candidate, inventory)
    rows = review_rows if independent else []
    audit = check_review_rows(targets, rows)
    keyed = {(row['domain'], row['ref']): row for row in rows}
    payload = candidate.payload
    compounds = payload.compounds
    edges = [edge for group in payload.lineages for edge in group.edges]
    source_groups = occurrence_groups(payload.structure_locators)
    cropped_evidence = [item for item in payload.evidence if item.bbox is not None]
    regions = {_region(item) for item in [*payload.structure_locators, *cropped_evidence]}

    def state(domain, ref, **kwargs):
        return _row_state(keyed.get((domain, ref)), **kwargs)

    compound_states = {compound.ref: state('structures', compound.ref) for compound in compounds}
    evidence_states = {item.ref: state('evidence', item.ref, evidence_crop=item.bbox is not None) for item in payload.evidence}
    link_states = {str(index): state('edge_evidence_links', str(index)) for index in range(len(payload.edge_evidence_links))}
    activity_states = []
    for index, activity in enumerate(payload.activities):
        dependencies = [compound_states[activity.compound_ref]]
        if activity.evidence_ref:
            dependencies.append(evidence_states[activity.evidence_ref])
        activity_states.append(_dependent(state('activities', str(index)), dependencies))
    edge_states = {}
    for lineage in payload.lineages:
        for edge in lineage.edges:
            dependencies = [compound_states[edge.parent_compound_ref], compound_states[edge.child_compound_ref]]
            for index, link in enumerate(payload.edge_evidence_links):
                if link.edge_ref == edge.ref:
                    dependencies.extend([evidence_states[link.evidence_ref], link_states[str(index)]])
            edge_states[edge.ref] = _dependent(state('edges', edge.ref, synthesis=lineage.lineage_type == 'synthesis'), dependencies)
    lineage_states = [
        _dependent(state('groups', group.ref), [*(compound_states[m.compound_ref] for m in group.members),
                    *(edge_states[e.ref] for e in group.edges)]) for group in payload.lineages
    ]
    screenshot_states = [
        _group_state([state('locators', item.ref) for item in group]) for group in source_groups
    ] + [evidence_states[item.ref] for item in cropped_evidence]
    domains = {
        'compounds': (compounds, list(compound_states.values())),
        'activities': (payload.activities, activity_states),
        'lineages': (payload.lineages, lineage_states),
        'edges': (edges, list(edge_states.values())),
        'evidence': (payload.evidence, list(evidence_states.values())),
        'screenshots': ([*source_groups, *cropped_evidence], screenshot_states),
    }
    flagged = {domain: {i for i, item in enumerate(items) if getattr(item, 'review_hint', None)}
               for domain, (items, _) in domains.items()}
    findings = []
    raw_findings = (producer_report or {}).get('findings', [])
    if isinstance(raw_findings, list):
        findings.extend(item for item in raw_findings if isinstance(item, dict))
    for item in findings:
        path = str(item.get('ref', item.get('path', '')))
        match = re.match(r'^payload\.(compounds|activities|lineages|evidence)\[(\d+)\]', path)
        if match:
            domain, index = match.group(1), int(match.group(2))
            if index < len(domains[domain][0]):
                flagged[domain].add(index)
        edge_match = re.match(r'^payload\.lineages\[(\d+)\]\.edges\[(\d+)\]', path)
        if edge_match:
            group_index, edge_index = map(int, edge_match.groups())
            if group_index < len(payload.lineages) and edge_index < len(payload.lineages[group_index].edges):
                flagged['edges'].add(sum(len(group.edges) for group in payload.lineages[:group_index]) + edge_index)
    entities = []
    for domain, (items, states) in domains.items():
        counts = Counter(states)
        if independent:
            flagged[domain].update(index for index, result in enumerate(states) if result in {'incorrect', 'uncertain'})
        entities.append({'domain': domain, 'total': len(items),
                         'supported': counts['supported'] if independent else None,
                         'incorrect': counts['incorrect'] if independent else None,
                         'uncertain': counts['uncertain'] if independent else None,
                         'unreviewed': counts['unreviewed'] if independent else len(items),
                         'flagged': len(flagged[domain])})

    findings.extend({'code': 'REVIEW_' + row['verdict'].upper() + '_' + row['domain'].upper(),
                     'ref': row['ref'], 'reason': row['reason']} for row in actionable_review_rows(candidate, rows))
    issues = Counter(str(item.get('code') or item.get('domain') or 'UNCLASSIFIED')[:128] for item in findings)
    highlights = []
    seen_codes = set()
    for item in findings:
        code = str(item.get('code') or item.get('domain') or 'UNCLASSIFIED')[:128]
        if code in seen_codes:
            continue
        seen_codes.add(code)
        highlights.append({'code': code, 'ref': str(item.get('ref') or item.get('path') or '')[:255],
                           'summary': str(item.get('reason') or item.get('message') or '')[:500]})
        if len(highlights) == 3:
            break
    return {
        'schema_version': 1, 'basis': 'independent_review' if independent else 'producer',
        'scientific_approval': False, 'entities': entities,
        'compound_coverage': {'known': coverage is not None,
            'covered': coverage['covered_count'] if coverage else None,
            'expected': coverage['required_count'] if coverage else None,
            'percent': _percent(coverage['covered_count'], coverage['required_count']) if coverage else None},
        'audit_coverage': {'known': independent, 'checked': audit['reviewed'] if independent else 0,
            'expected': audit['expected'] if independent else None,
            'percent': _percent(audit['reviewed'], audit['expected']) if independent else None},
        'audit_scope': 'candidate_and_inventory' if inventory else 'candidate_only',
        'issue_groups': [{'code': code, 'count': count} for code, count in sorted(issues.items(), key=lambda pair: (-pair[1], pair[0]))],
        'highlights': highlights, 'unique_crop_regions': len(regions),
        'screenshot_counts': {'structure_occurrences': len(source_groups), 'evidence_crops': len(cropped_evidence),
                              'unique_crop_regions': len(regions)},
        'limitations': ['AI assessment, not human approval or whole-paper accuracy.',
            'Compound coverage is label matching against the declared inventory; source completeness is not established.',
            'Supported requires explicit core-field checks; partial or unstructured checks remain uncertain.'],
    }
