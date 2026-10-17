from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from app.compounds.models import Compound
from app.structures.models import Structure
from app.activities.models import Activity
from app.lineages.models import Lineage, LineageMember, LineageEdge
from app.evidence.models import Evidence, EdgeEvidenceLink
from app.structure_images.models import StructureSourceImage
from app.workspaces.models import PaperWorkspace, ChangeEvent


def seed(f):
    with f.session_factory.begin() as session:
        a = Compound(paper_id=f.paper_id, workspace_id=f.workspace_id, compound_label='A', display_name='Original', description='Synthetic description', created_by_kind='reviewer', sort_order=0)
        b = Compound(paper_id=f.paper_id, workspace_id=f.workspace_id, compound_label='B', created_by_kind='reviewer', sort_order=1)
        session.add_all([a, b]); session.flush()
        e = Evidence(paper_id=f.paper_id, workspace_id=f.workspace_id, kind='text', source_sha256='a'*64, page_number=1, quoted_text='Synthetic fixture', created_by_kind='reviewer')
        l = Lineage(paper_id=f.paper_id, workspace_id=f.workspace_id, lineage_label='Series', lineage_type='sar', sort_order=0, created_by_kind='reviewer')
        session.add_all([e, l]); session.flush()
        session.add_all([
            Structure(paper_id=f.paper_id, workspace_id=f.workspace_id, compound_id=a.id, smiles='CC', canonical_smiles='CC', status='reviewer_confirmed', input_method='manual_smiles'),
            Activity(paper_id=f.paper_id, workspace_id=f.workspace_id, compound_id=a.id, evidence_id=e.id, assay_name='Synthetic assay', metric='IC50', operator='=', value=12, unit='nM', sort_order=0),
            StructureSourceImage(paper_id=f.paper_id, workspace_id=f.workspace_id, compound_id=a.id, source_sha256='a'*64, page_number=1, x0=.1, y0=.1, x1=.2, y1=.2, crop_status='pending'),
            LineageMember(paper_id=f.paper_id, workspace_id=f.workspace_id, lineage_id=l.id, compound_id=a.id, role='root', sort_order=0),
            LineageMember(paper_id=f.paper_id, workspace_id=f.workspace_id, lineage_id=l.id, compound_id=b.id, role='terminal', sort_order=1),
        ]); session.flush()
        edge = LineageEdge(paper_id=f.paper_id, workspace_id=f.workspace_id, lineage_id=l.id, parent_compound_id=a.id, child_compound_id=b.id, relation_type='lead_optimization', modification_summary='Synthetic change', review_status='reviewer_confirmed', sort_order=0)
        session.add(edge); session.flush()
        session.add(EdgeEvidenceLink(paper_id=f.paper_id, workspace_id=f.workspace_id, edge_id=edge.id, evidence_id=e.id, role='supports'))
        return a.id, b.id, l.id, edge.id, e.id


def paste(f, csrf, kind, source_id, label, version=1, **extra):
    return f.client.post(f'/api/v2/workspaces/{f.workspace_id}/clipboard/{kind}',
        json={'expected_workspace_version': version, 'source_id': str(source_id), 'label': label, **extra}, headers={'X-CSRF-Token': csrf})


def test_compound_paste_copies_aggregate_as_draft_without_identity_or_memberships(workspace_fixture):
    f = workspace_fixture
    a, _, _, _, evidence_id = seed(f)
    result = paste(f, f.login('workspace.reviewer'), 'compound', a, 'New')
    assert result.status_code == 201, result.text
    data = result.json(); copied_id = UUID(data['entity_id'])
    assert data['workspace_version'] == 2
    assert copied_id != a
    with f.session_factory() as session:
        copied = session.get(Compound, copied_id)
        assert copied.compound_label == 'New' and copied.display_name is None
        assert copied.description == 'Synthetic description'
        structure = session.scalar(select(Structure).where(Structure.compound_id == copied_id))
        assert structure.status.value == 'draft' and structure.canonical_smiles == 'CC'
        activity = session.scalar(select(Activity).where(Activity.compound_id == copied_id))
        assert activity.evidence_id == evidence_id and activity.value == 12
        assert session.scalar(select(func.count()).select_from(StructureSourceImage).where(StructureSourceImage.compound_id == copied_id)) == 1
        assert session.scalar(select(func.count()).select_from(LineageMember).where(LineageMember.compound_id == copied_id)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEvent).where(ChangeEvent.workspace_id == f.workspace_id)) == 1
        from app.workspaces.snapshot import build_paper_snapshot
        from app.publications.comparison import reconstruct_reviewer_baseline
        events = list(session.scalars(select(ChangeEvent).where(ChangeEvent.workspace_id == f.workspace_id)))
        assert events[0].before_value['snapshot']['workspace_version'] == 1
        assert events[0].after_value['snapshot']['workspace_version'] == 2
        baseline, warnings = reconstruct_reviewer_baseline(build_paper_snapshot(session, f.workspace_id), events)
        assert not warnings
        assert copied_id not in {UUID(row['id']) for row in baseline['compounds']}


def test_lineage_paste_reuses_compounds_and_evidence_but_clones_members_edges(workspace_fixture):
    f = workspace_fixture
    a, b, source, original_edge, evidence_id = seed(f)
    result = paste(f, f.login('workspace.reviewer'), 'lineage', source, 'Series')
    assert result.status_code == 201, result.text
    copied_id = UUID(result.json()['entity_id'])
    with f.session_factory() as session:
        assert copied_id != source
        assert session.get(Lineage, copied_id).lineage_label == 'Series'
        members = list(session.scalars(select(LineageMember).where(LineageMember.lineage_id == copied_id)))
        assert {m.compound_id for m in members} == {a, b}
        edge = session.scalar(select(LineageEdge).where(LineageEdge.lineage_id == copied_id))
        assert edge.id != original_edge and edge.review_status.value == 'draft'
        assert edge.modification_summary == 'Synthetic change'
        link = session.scalar(select(EdgeEvidenceLink).where(EdgeEvidenceLink.edge_id == edge.id))
        assert link.evidence_id == evidence_id
        assert session.scalar(select(func.count()).select_from(Compound)) == 2


@pytest.mark.parametrize('kind', ['compound', 'lineage'])
def test_paste_rejects_blank_names_wrong_sources_stale_versions_and_permissions(workspace_fixture, kind):
    f = workspace_fixture
    a, _, lineage, _, _ = seed(f)
    source = a if kind == 'compound' else lineage
    csrf = f.login('workspace.reviewer')
    assert paste(f, csrf, kind, source, '   ').status_code == 422
    assert paste(f, csrf, kind, uuid4(), 'New').status_code == 404
    assert paste(f, csrf, kind, source, 'New', version=99).status_code == 409
    assert paste(f, '', kind, source, 'New').status_code == 403
    assert paste(f, f.login('workspace.other'), kind, source, 'New').status_code == 404
    assert paste(f, f.login('workspace.admin'), kind, source, 'New').status_code == 403
    with f.session_factory() as session:
        assert session.get(PaperWorkspace, f.workspace_id).version == 1


def test_compound_paste_rejects_duplicate_identifier_but_accepts_duplicate_display_name(workspace_fixture):
    f = workspace_fixture
    a, _, _, _, _ = seed(f)
    csrf = f.login('workspace.reviewer')
    duplicate = paste(f, csrf, 'compound', a, 'A')
    assert duplicate.status_code == 409
    assert duplicate.json()['code'] == 'COMPOUND_LABEL_CONFLICT'
    assert paste(f, csrf, 'compound', a, 'C', display_name='Original').status_code == 201


def test_paste_rejects_a_source_from_another_workspace_and_readonly_destination(workspace_fixture):
    from app.workspaces.models import ReviewTask, WorkspaceState
    from app.papers.models import Paper
    f = workspace_fixture
    a, _, _, _, _ = seed(f)
    with f.session_factory.begin() as session:
        other_paper = session.scalar(select(Paper).where(Paper.id != f.paper_id))
        other_task = ReviewTask(paper_id=other_paper.id, assigned_reviewer_id=f.reviewer_id, created_by_id=f.admin_id, status='assigned', version=1)
        session.add(other_task); session.flush()
        other_workspace = PaperWorkspace(paper_id=other_paper.id, review_task_id=other_task.id, state='editing', version=1)
        session.add(other_workspace); session.flush()
        other_compound = Compound(paper_id=other_paper.id, workspace_id=other_workspace.id, compound_label='Foreign', created_by_kind='reviewer', sort_order=0)
        session.add(other_compound); session.flush()
        foreign_id = other_compound.id
    csrf = f.login('workspace.reviewer')
    assert paste(f, csrf, 'compound', foreign_id, 'New').status_code == 404
    with f.session_factory.begin() as session:
        session.get(PaperWorkspace, f.workspace_id).state = WorkspaceState.SUBMITTED
    assert paste(f, csrf, 'compound', a, 'New').status_code == 409
