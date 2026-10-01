"""Offline graph diagnostics do not decide scientific grouping or modify candidates."""
import hashlib
import json
from pathlib import Path

import pytest

from app.ai_prefill.assistance_contracts import CandidateEnvelope
from app.ai_prefill.assistance_coverage import CompoundInventory
from app.ai_prefill.assistance_self_check import (
    SOURCE_REVIEW_CHECKS, SourceSelfReview, self_check_candidate,
)


def candidate(lineages=(), labels=('a', 'b', 'c', 'd', 'e')):
    path = Path(__file__).resolve().parents[4] / 'docs/ai-prefill/examples/candidate-v1.json'
    data = json.loads(path.read_text())
    data['hashes'] = None
    data['payload'] = {
        'schema_version': 1,
        'compounds': [{'ref': x, 'compound_label': x, 'structure': {'smiles': 'CCO'}} for x in labels],
        'lineages': list(lineages),
    }
    return CandidateEnvelope.model_validate(data)


def lineage(kind, pairs, roles, ref='l1', description=None):
    return dict(ref=ref, lineage_label=ref, lineage_type=kind, description=description,
                members=[dict(compound_ref=x, role=role) for x, role in roles.items()],
                edges=[dict(ref=f'{ref}-e{i}', parent_compound_ref=a, child_compound_ref=b,
                            relation_type='comparison' if kind == 'sar' else 'reaction')
                       for i, (a, b) in enumerate(pairs)])


def report(c):
    # Test through the existing self-check entry point so integration is exercised.
    raw = c.model_dump_json().encode()
    inv = CompoundInventory.model_validate(dict(
        inventory_version=1, source=c.source.model_dump(), scope='fixture inventory',
        reviewed_by='test fixture', entries=[dict(label=x.compound_label, required=True,
        role='fixture', source_locator='fixture') for x in c.payload.compounds]))
    review = SourceSelfReview.model_validate(dict(self_review_version=1,
        candidate_file_sha256=hashlib.sha256(raw).hexdigest(), reviewer_type='producer_self_check',
        checks=[dict(check_id=x, status='checked', details='Fixture source review only.',
                     source_locations=['fixture']) for x in SOURCE_REVIEW_CHECKS]))
    return self_check_candidate(c, inv, candidate_file_bytes=raw, self_review=review)


def test_disconnected_components_and_isolates_are_visible_without_mutation():
    c = candidate([lineage('synthesis', [('a', 'b'), ('c', 'd')],
                          dict(a='root', b='terminal', c='root', d='terminal', e='unspecified'))])
    before = c.model_dump_json()
    r = report(c)
    group = r['lineage_diagnostics']['lineages'][0]
    assert group['weakly_connected_components'] == [['a', 'b'], ['c', 'd'], ['e']]
    assert group['isolated_compound_refs'] == ['e']
    assert group['role_conflicts'] == []
    assert {'LINEAGE_DISCONNECTED', 'LINEAGE_ISOLATED_MEMBERS'} <= {x['code'] for x in r['issues']}
    assert c.model_dump_json() == before
    assert r['status'] == 'ready_for_independent_review'
    assert r['scientific_approval'] is False


def test_synthesis_roles_use_local_topology_and_allow_convergent_roots():
    c = candidate([lineage('synthesis', [('a', 'c'), ('b', 'c'), ('c', 'd')],
                          dict(a='root', b='root', c='terminal', d='intermediate', e='root'))])
    r = report(c)
    conflicts = r['lineage_diagnostics']['lineages'][0]['role_conflicts']
    assert [(x['compound_ref'], x['declared_role'], x['topological_role']) for x in conflicts] == [
        ('c', 'terminal', 'intermediate'), ('d', 'intermediate', 'terminal'), ('e', 'root', 'isolated')]
    issues = [x for x in r['issues'] if x['code'] == 'SYNTHESIS_ROLE_TOPOLOGY_CONFLICT']
    assert len(issues) == 1 and issues[0]['severity'] == 'review'
    assert r['status'] == 'ready_for_independent_review'


def test_sar_roles_are_not_given_synthesis_semantics():
    c = candidate([lineage('sar', [('a', 'b'), ('b', 'c')], dict(a='terminal', b='root', c='root'))])
    group = report(c)['lineage_diagnostics']['lineages'][0]
    assert group['role_conflicts'] == []
    assert all(x['topological_role'] is None for x in group['members'])


@pytest.mark.parametrize('kind', ['sar', 'synthesis'])
def test_cycles_report_only_cycle_members_not_downstream_nodes(kind):
    c = candidate([lineage(kind, [('a', 'b'), ('b', 'a'), ('b', 'c')],
                          dict(a='unspecified', b='unspecified', c='unspecified'))])
    r = report(c)
    assert r['lineage_diagnostics']['lineages'][0]['cyclic_components'] == [['a', 'b']]
    assert any(x['code'] == 'LINEAGE_CYCLE' and x['severity'] == 'review' for x in r['issues'])


def test_participation_distinguishes_membership_with_edges_and_isolated_members():
    c = candidate([
        lineage('sar', [('a', 'b')], dict(a='root', b='unspecified', c='unspecified'), ref='sar'),
        lineage('synthesis', [('b', 'c')], dict(b='root', c='terminal'), ref='syn'),
    ])
    d = report(c)['lineage_diagnostics']
    p = {x['compound_ref']: x for x in d['compound_participation']}
    assert p['a']['sar']['status'] == 'with_edges'
    assert p['a']['synthesis']['status'] == 'absent'
    assert p['c']['sar']['status'] == 'isolated_only'
    assert p['c']['synthesis']['status'] == 'with_edges'
    assert d['nonmembers_by_type'] == {'sar': ['d', 'e'], 'synthesis': ['a', 'd', 'e']}
    assert d['global_nonmember_compound_refs'] == ['d', 'e']


def test_description_does_not_automatically_clear_review_or_determine_grouping():
    c = candidate([lineage('sar', [('a', 'b'), ('c', 'd')],
                          dict(a='root', b='terminal', c='root', d='terminal'),
                          description='Reviewed: valid independent components; disconnected allowed.')])
    r = report(c)
    assert any(x['code'] == 'LINEAGE_DISCONNECTED' for x in r['issues'])
    assert len(r['lineage_diagnostics']['lineages']) == 1


def test_empty_lineage_and_no_membership_are_reported_without_crashing():
    r = report(candidate([lineage('sar', [], {})]))
    group = r['lineage_diagnostics']['lineages'][0]
    assert group['weakly_connected_components'] == []
    assert group['cyclic_components'] == []
    assert r['lineage_diagnostics']['global_nonmember_compound_refs'] == ['a', 'b', 'c', 'd', 'e']


def test_convergent_dag_and_repeated_edges_are_not_cycles_or_role_conflicts():
    c = candidate([lineage('synthesis', [('a', 'b'), ('a', 'c'), ('b', 'd'), ('c', 'd'), ('c', 'd')],
                          dict(a='root', b='intermediate', c='intermediate', d='terminal'))])
    group = report(c)['lineage_diagnostics']['lineages'][0]
    assert group['cyclic_components'] == []
    assert group['role_conflicts'] == []
    assert group['weakly_connected_components'] == [['a', 'b', 'c', 'd']]


def test_shared_compound_keeps_each_groups_participation_and_local_role():
    c = candidate([
        lineage('synthesis', [('a', 'b'), ('b', 'c')], dict(a='root', b='intermediate', c='terminal'), ref='syn1'),
        lineage('synthesis', [('b', 'd')], dict(b='root', d='terminal', c='unspecified'), ref='syn2'),
    ])
    d = report(c)['lineage_diagnostics']
    assert all(not x['role_conflicts'] for x in d['lineages'])
    p = {x['compound_ref']: x for x in d['compound_participation']}
    assert p['c']['synthesis'] == dict(status='with_edges', member_lineage_refs=['syn1', 'syn2'],
                                     edge_lineage_refs=['syn1'], isolated_lineage_refs=['syn2'])
    assert len(d['lineages']) == 2  # A shared member does not merge scientific groups.


def test_unclassified_legacy_members_are_not_global_nonmembers_or_given_roles():
    c = candidate([lineage('unspecified', [('a', 'b')], dict(a='terminal', b='root'))])
    r = report(c)
    d = r['lineage_diagnostics']
    assert d['global_nonmember_compound_refs'] == ['c', 'd', 'e']
    assert d['nonmembers_by_type']['sar'] == ['a', 'b', 'c', 'd', 'e']
    assert d['lineages'][0]['role_conflicts'] == []
    assert any(x['code'] == 'LINEAGE_TYPE_MISSING' and x['severity'] == 'blocking' for x in r['issues'])


def test_long_route_diagnostics_do_not_require_recursive_graph_traversal():
    from app.ai_prefill.assistance_lineage import diagnose_lineages
    labels = [f'c{i}' for i in range(1100)]
    c = candidate([lineage('synthesis', list(zip(labels, labels[1:])),
                          {x: 'unspecified' for x in labels})], labels=labels)
    d = diagnose_lineages(c)
    assert len(d['lineages'][0]['weakly_connected_components']) == 1
    assert d['lineages'][0]['cyclic_components'] == []
