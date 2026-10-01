"""Deterministic candidate graph diagnostics; no source or scientific interpretation."""
from __future__ import annotations

from app.ai_prefill.assistance_contracts import CandidateEnvelope


def _component(start: str, adjacency: dict[str, set[str]], seen: set[str]) -> list[str]:
    pending, members = [start], []
    seen.add(start)
    while pending:
        node = pending.pop()
        members.append(node)
        for neighbor in sorted(adjacency[node]):
            if neighbor not in seen:
                seen.add(neighbor)
                pending.append(neighbor)
    return sorted(members)


def _components(adjacency: dict[str, set[str]]) -> list[list[str]]:
    seen: set[str] = set()
    return [_component(node, adjacency, seen) for node in sorted(adjacency) if node not in seen]


def _cycles(outgoing: dict[str, set[str]], incoming: dict[str, set[str]]) -> list[list[str]]:
    # Iterative Kosaraju avoids recursion limits on long valid synthetic routes.
    seen: set[str] = set()
    finished = []
    for start in sorted(outgoing):
        if start in seen:
            continue
        seen.add(start)
        stack = [(start, iter(sorted(outgoing[start])))]
        while stack:
            node, neighbors = stack[-1]
            neighbor = next(neighbors, None)
            if neighbor is None:
                finished.append(node)
                stack.pop()
            elif neighbor not in seen:
                seen.add(neighbor)
                stack.append((neighbor, iter(sorted(outgoing[neighbor]))))
    seen.clear()
    cycles = []
    for node in reversed(finished):
        if node not in seen:
            component = _component(node, incoming, seen)
            if len(component) > 1 or node in outgoing[node]:
                cycles.append(component)
    return sorted(cycles)


def diagnose_lineages(candidate: CandidateEnvelope) -> dict:
    """Inspect declared groups, preserving all membership, roles and edge direction.

    Components, cycles and absent participation require interpretation. Even a
    synthesis role conflict is review-only: this function never edits annotations
    or claims source support. Unspecified roles and SAR roles are not inferred.
    """
    groups, issues = [], []
    participation = {
        c.ref: {kind: {'member_lineage_refs': [], 'edge_lineage_refs': [],
                      'isolated_lineage_refs': []} for kind in ('sar', 'synthesis')}
        for c in candidate.payload.compounds
    }
    all_members = set()

    def review(code, path, message, **details):
        issues.append(dict(code=code, severity='review', path=path,
                           message=message, details=details))

    for i, lineage in enumerate(candidate.payload.lineages):
        path = f'payload.lineages[{i}]'
        outgoing = {m.compound_ref: set() for m in lineage.members}
        incoming = {m.compound_ref: set() for m in lineage.members}
        all_members.update(outgoing)
        for edge in lineage.edges:
            outgoing[edge.parent_compound_ref].add(edge.child_compound_ref)
            incoming[edge.child_compound_ref].add(edge.parent_compound_ref)
        undirected = {ref: outgoing[ref] | incoming[ref] for ref in outgoing}
        components = _components(undirected)
        isolated = sorted(ref for ref in outgoing if not undirected[ref])
        cycles = _cycles(outgoing, incoming)
        members, conflicts = [], []
        for member in lineage.members:
            ref = member.compound_ref
            before, after = len(incoming[ref]), len(outgoing[ref])
            topology = None
            if lineage.lineage_type == 'synthesis':
                topology = ('intermediate' if before and after else 'terminal' if before
                            else 'root' if after else 'isolated')
            item = dict(compound_ref=ref, declared_role=member.role,
                        incoming_neighbor_count=before, outgoing_neighbor_count=after,
                        topological_role=topology)
            members.append(item)
            if topology is not None and member.role != 'unspecified' and member.role != topology:
                conflicts.append(item.copy())
            if lineage.lineage_type in ('sar', 'synthesis'):
                p = participation[ref][lineage.lineage_type]
                p['member_lineage_refs'].append(lineage.ref)
                p['edge_lineage_refs' if before or after else 'isolated_lineage_refs'].append(lineage.ref)
        groups.append(dict(lineage_ref=lineage.ref, lineage_label=lineage.lineage_label,
                           lineage_type=lineage.lineage_type, member_count=len(outgoing),
                           edge_count=len(lineage.edges), weakly_connected_components=components,
                           isolated_compound_refs=isolated, cyclic_components=cycles,
                           members=members, role_conflicts=conflicts))
        if len(components) > 1:
            review('LINEAGE_DISCONNECTED', path,
                   'Explain and review the group scope and disconnected components; do not add edges or split groups solely for connectivity.',
                   lineage_ref=lineage.ref, components=components)
        if isolated:
            review('LINEAGE_ISOLATED_MEMBERS', path + '.members',
                   'Review why these members have no incident edges; retain compounds and do not invent participation.',
                   lineage_ref=lineage.ref, compound_refs=isolated)
        if cycles:
            review('LINEAGE_CYCLE', path + '.edges',
                   'Review directed cycles in their relationship context; do not delete justified comparisons merely to obtain a tree.',
                   lineage_ref=lineage.ref, cyclic_components=cycles)
        if conflicts:
            review('SYNTHESIS_ROLE_TOPOLOGY_CONFLICT', path + '.members',
                   'Declared synthesis roles disagree with this group topology; reconcile annotations with source context, without automatic overwrites.',
                   lineage_ref=lineage.ref, conflicts=conflicts)

    records = []
    nonmembers = {'sar': [], 'synthesis': []}
    for compound in candidate.payload.compounds:
        record = dict(compound_ref=compound.ref, compound_label=compound.compound_label)
        for kind in ('sar', 'synthesis'):
            p = participation[compound.ref][kind]
            p['status'] = ('with_edges' if p['edge_lineage_refs'] else
                           'isolated_only' if p['member_lineage_refs'] else 'absent')
            record[kind] = p
            if p['status'] == 'absent':
                nonmembers[kind].append(compound.ref)
        records.append(record)
    for kind, refs in nonmembers.items():
        if refs:
            review('COMPOUNDS_WITHOUT_LINEAGE_MEMBERSHIP', 'payload.compounds',
                   'Record why each compound does not participate in this lineage type, with review status and source context or explicit uncertainty; absence is not automatically an extraction error.',
                   lineage_type=kind, compound_refs=refs)
    return dict(
        diagnostic_version=1, scientific_approval=False, lineages=groups,
        compound_participation=records, nonmembers_by_type=nonmembers,
        global_nonmember_compound_refs=[c.ref for c in candidate.payload.compounds if c.ref not in all_members],
        issues=issues,
        limitations=[
            'Topology only: descriptions and source support are not semantically evaluated.',
            'Connectivity or a shared reactant does not establish a scientific family.',
            'SAR roles, selected leads and whole-paper relationship completeness are not inferred.',
            'No candidates, roles, edges or group assignments are modified.',
        ],
    )
