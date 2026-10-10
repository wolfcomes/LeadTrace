from uuid import UUID, uuid4

from sqlalchemy import select

from app.audit.models import AuditEvent
from app.audit.service import AuditService
from app.papers.models import Paper
from app.workspaces.models import PaperWorkspace, ReviewTask


def removal_body(f):
    return dict(reason='Confirmed review; outside original optimization scope',
                confirm_paper_key='LT-JMC-2024-67-05-001',
                expected_workspace_id=str(f.workspace_id),
                expected_workspace_version=1, expected_task_version=1)


def remove(f, body=None, headers=None):
    return f.client.request('DELETE', f'/api/v2/admin/papers/{f.paper_id}',
                            json=body or removal_body(f), headers=headers)


def test_removal_requires_admin_csrf_and_current_identity(workspace_fixture):
    f = workspace_fixture
    assert remove(f).status_code == 401
    token = f.login('workspace.reviewer')
    assert remove(f, headers={'X-CSRF-Token': token}).status_code == 403
    token = f.login('workspace.admin')
    assert remove(f).status_code == 403
    headers = {'X-CSRF-Token': token}
    for changes in ({'expected_workspace_version': 2}, {'expected_task_version': 2},
                    {'expected_workspace_id': str(uuid4())}, {'confirm_paper_key': 'wrong'}):
        result = remove(f, {**removal_body(f), **changes}, headers)
        assert result.status_code == 409, result.text
    assert remove(f, {**removal_body(f), 'reason': '   '}, headers).status_code == 422
    with f.session_factory() as session:
        assert session.get(PaperWorkspace, f.workspace_id).version == 1
        assert session.get(ReviewTask, f.task_id).status == 'assigned'


def test_removal_hides_all_entry_points_and_retains_rows(workspace_fixture):
    f = workspace_fixture
    headers = {'X-CSRF-Token': f.login('workspace.admin')}
    with f.session_factory() as session:
        before = session.get(Paper, f.paper_id).title
    result = remove(f, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['paper_id'] == str(f.paper_id)
    assert result.json()['removed_at']
    catalog = f.client.get('/api/v2/admin/papers').json()
    assert catalog['total'] == 1
    assert f.client.get('/api/v2/admin/papers', params={'search': '4c0001'}).json()['total'] == 0
    for path in (f'/api/v2/admin/papers/{f.paper_id}',
                 f'/api/v2/admin/papers/{f.paper_id}/management',
                 f'/api/v2/workspaces/{f.workspace_id}',
                 f'/api/v2/papers/{f.paper_id}/source-pdf',
                 f'/api/v1/assets/{f.asset_id}',
                 f'/api/v1/assets/{f.asset_id}/content',
                 f'/api/v1/admin/files/{f.asset_id}/references'):
        assert f.client.get(path).status_code == 404, path
    files = f.client.get('/api/v1/admin/files').json()
    assert all(row['id'] != str(f.asset_id) for row in files)
    audit = f.client.get('/api/v1/admin/audit', params={'action':'paper.remove'})
    assert audit.status_code == 200
    assert any(event['paper_id'] == str(f.paper_id) for event in audit.json())
    assert remove(f, headers=headers).status_code == 404
    assigned = f.client.post(f'/api/v2/admin/papers/{f.paper_id}/assign',
                            json={'reviewer_id': str(f.reviewer_id)}, headers=headers)
    assert assigned.status_code == 404
    with f.session_factory() as session:
        paper = session.get(Paper, f.paper_id)
        assert paper.title == before
        assert paper.removed_at is not None
        assert paper.removed_by_id == f.admin_id
        workspace = session.get(PaperWorkspace, f.workspace_id)
        assert workspace.version == 1 and workspace.state == 'editing'
        task = session.get(ReviewTask, f.task_id)
        assert task.status == 'archived' and task.version == 2
        assert task.assigned_reviewer_id == f.reviewer_id
        events = list(session.scalars(select(AuditEvent).where(AuditEvent.paper_id == f.paper_id)))
        assert len(events) == 1 and events[0].action == 'paper.remove'
        assert AuditService().verify_chain(session).valid
        other = session.scalar(select(Paper).where(Paper.id != f.paper_id))
        assert other.removed_at is None
    f.login('workspace.reviewer')
    assert f.client.get('/api/v2/review/tasks').json()['items'] == []


def test_open_ai_job_blocks_removal_then_completed_job_is_hidden(workspace_fixture, monkeypatch):
    from app.ai_tasks.models import AiTask
    f = workspace_fixture
    settings = f.client.app.state.settings
    settings.ai_task_worker_enabled = True
    settings.ai_task_presets = [{'id':'synthetic','label':'Test','adapter':'codex','model':'gpt-test','efforts':['high'],'default_effort':'high'}]
    monkeypatch.setattr('app.ai_tasks.service.shutil.which', lambda _: '/bin/synthetic')
    headers = {'X-CSRF-Token': f.login('workspace.admin')}
    body = dict(action='prefill', preset_id='synthetic', reasoning_effort='high',
                expected_workspace_id=str(f.workspace_id), expected_task_version=1,
                expected_workspace_version=1, idempotency_key=str(uuid4()))
    response = f.client.post(f'/api/v2/admin/papers/{f.paper_id}/ai-tasks', json=body, headers=headers)
    assert response.status_code == 200, response.text
    job_id = response.json()['id']
    for state in ['queued', 'preparing', 'running', 'validating', 'cancel_requested']:
        with f.session_factory.begin() as session:
            session.get(AiTask, UUID(job_id)).state = state
        response = remove(f, headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()['code'] == 'PAPER_TASK_ACTIVE'
    with f.session_factory.begin() as session:
        session.get(AiTask, UUID(job_id)).state = 'failed'
    assert remove(f, headers=headers).status_code == 200
    assert f.client.get('/api/v2/admin/ai-tasks').json()['items'] == []
    for suffix in ['', '/report']:
        assert f.client.get(f'/api/v2/admin/ai-tasks/{job_id}{suffix}').status_code == 404
    for suffix, payload in [('retry', {'idempotency_key':str(uuid4())}), ('deliver', None), ('cancel', None)]:
        response = f.client.post(f'/api/v2/admin/ai-tasks/{job_id}/{suffix}', json=payload, headers=headers)
        assert response.status_code == 404, response.text
    response = f.client.post(f'/api/v2/admin/papers/{f.paper_id}/ai-tasks', json={**body, 'idempotency_key':str(uuid4())}, headers=headers)
    assert response.status_code in {404, 409}
    with f.session_factory() as session:
        assert session.get(AiTask, UUID(job_id)).state == 'failed'
    settings.ai_task_worker_enabled = False


def test_removed_paper_rejects_legacy_queue_and_hides_derived_files(workspace_fixture):
    import pytest
    from app.ai_prefill.service import AiPrefillService, AiPrefillNotFoundError
    from app.assets.models import Asset, AssetCategory, AssetAccessLevel, AssetIntegrityState
    f = workspace_fixture
    with f.session_factory.begin() as session:
        asset = Asset(storage_key='managed/removed/depiction.svg', original_filename='depiction.svg',
            sha256='c'*64, byte_size=100, mime_type='image/svg+xml',
            category=AssetCategory.RDKIT_STRUCTURE, access_level=AssetAccessLevel.ADMIN,
            integrity_state=AssetIntegrityState.VERIFIED, source_asset_id=f.asset_id,
            derivation_metadata={}, source_metadata={})
        session.add(asset)
        session.flush()
        asset_id = asset.id
    headers = {'X-CSRF-Token': f.login('workspace.admin')}
    assert f.client.get(f'/api/v1/assets/{asset_id}').status_code == 200
    assert remove(f, headers=headers).status_code == 200
    assert f.client.get(f'/api/v1/assets/{asset_id}').status_code == 404
    assert f.client.get(f'/api/v2/admin/papers/{f.paper_id}/ai-prefill').status_code == 404
    with f.session_factory.begin() as session:
        with pytest.raises(AiPrefillNotFoundError):
            AiPrefillService().queue(session, workspace_id=f.workspace_id,
                requested_by_id=f.admin_id, engine='test', engine_version='1')


def test_scientific_rows_are_retained_but_child_ids_and_mutations_are_hidden(workspace_fixture):
    from app.compounds.models import Compound
    f = workspace_fixture
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    endpoint = f'/api/v2/workspaces/{f.workspace_id}/compounds'
    response = f.client.post(endpoint, json={'expected_workspace_version':1, 'compound_label':'1'}, headers=headers)
    assert response.status_code == 201, response.text
    compound_id = response.json()['compound']['id']
    assert f.client.get(f'/api/v2/compounds/{compound_id}/structure').status_code == 200
    headers = {'X-CSRF-Token': f.login('workspace.admin')}
    assert remove(f, {**removal_body(f), 'expected_workspace_version':2}, headers).status_code == 200
    headers = {'X-CSRF-Token': f.login('workspace.reviewer')}
    for path in [endpoint, f'/api/v2/compounds/{compound_id}/structure',
                 f'/api/v2/compounds/{compound_id}/source-images',
                 f'/api/v2/workspaces/{f.workspace_id}/review-progress',
                 f'/api/v2/workspaces/{f.workspace_id}/ai-provenance']:
        response = f.client.get(path)
        assert response.status_code == 404, (path, response.text)
    response = f.client.patch(f'/api/v2/compounds/{compound_id}',
        json={'expected_workspace_version':2,'display_name':'must not write'}, headers=headers)
    assert response.status_code == 404
    with f.session_factory() as session:
        assert session.get(Compound, UUID(compound_id)).compound_label == '1'
        assert session.get(Compound, UUID(compound_id)).display_name is None
        assert session.get(PaperWorkspace, f.workspace_id).version == 2


def test_legacy_active_run_blocks_removal(workspace_fixture):
    from app.ai_prefill.service import AiPrefillService
    from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
    f = workspace_fixture
    with f.session_factory.begin() as session:
        run = AiPrefillService().queue(session, workspace_id=f.workspace_id,
            requested_by_id=f.admin_id, engine='synthetic', engine_version='1').run
        run_id = run.id
    headers = {'X-CSRF-Token': f.login('workspace.admin')}
    for state in [AiExtractionRunStatus.QUEUED, AiExtractionRunStatus.RUNNING]:
        with f.session_factory.begin() as session:
            session.get(AiExtractionRun, run_id).status = state
        response = remove(f, headers=headers)
        assert response.status_code == 409 and response.json()['code'] == 'PAPER_TASK_ACTIVE'
        with f.session_factory() as session:
            assert session.get(Paper, f.paper_id).removed_at is None
    with f.session_factory.begin() as session:
        session.get(AiExtractionRun, run_id).status = AiExtractionRunStatus.FAILED
    assert remove(f, headers=headers).status_code == 200


def test_removed_historical_asset_references_are_hidden(workspace_fixture):
    from app.assets.models import Asset, AssetCategory, AssetAccessLevel, AssetIntegrityState
    from app.workspaces.models import ChangeActorKind, ChangeEvent
    f = workspace_fixture
    with f.session_factory.begin() as session:
        asset = Asset(storage_key='managed/history/old.svg', original_filename='old.svg',
            sha256='d'*64, byte_size=100, mime_type='image/svg+xml',
            category=AssetCategory.RDKIT_STRUCTURE, access_level=AssetAccessLevel.ADMIN,
            integrity_state=AssetIntegrityState.VERIFIED, derivation_metadata={}, source_metadata={})
        session.add(asset)
        session.flush()
        asset_id = asset.id
        session.add(ChangeEvent(paper_id=f.paper_id, workspace_id=f.workspace_id,
            entity_type='structure', entity_id=uuid4(), action='structure.update',
            before_value={'depiction_asset_id':str(asset_id)}, after_value={'depiction_asset_id':None},
            actor_kind=ChangeActorKind.REVIEWER, actor_id=f.reviewer_id))
    headers = {'X-CSRF-Token': f.login('workspace.admin')}
    assert f.client.get(f'/api/v1/assets/{asset_id}').status_code == 200
    assert remove(f, headers=headers).status_code == 200
    assert f.client.get(f'/api/v1/assets/{asset_id}').status_code == 404


def test_shared_asset_stays_visible_without_removed_scientific_references(workspace_fixture):
    from app.assets.models import Asset, AssetCategory, AssetAccessLevel, AssetIntegrityState
    from app.workspaces.models import ChangeActorKind
    from app.compounds.models import Compound
    from app.structures.models import Structure, StructureInputMethod, StructureStatus
    f = workspace_fixture
    with f.session_factory.begin() as session:
        asset = Asset(storage_key='managed/shared.svg', original_filename='shared.svg', sha256='e'*64,
            byte_size=100, mime_type='image/svg+xml', category=AssetCategory.RDKIT_STRUCTURE,
            access_level=AssetAccessLevel.ADMIN, integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={}, source_metadata={})
        session.add(asset); session.flush(); asset_id = asset.id
        compound = Compound(paper_id=f.paper_id,workspace_id=f.workspace_id,compound_label='1',
            sort_order=0,created_by_kind=ChangeActorKind.REVIEWER)
        session.add(compound); session.flush()
        structure = Structure(paper_id=f.paper_id,workspace_id=f.workspace_id,compound_id=compound.id,
            input_method=StructureInputMethod.MANUAL_SMILES,smiles='C',canonical_smiles='C',
            status=StructureStatus.DRAFT,depiction_asset_id=asset_id,created_by_kind=ChangeActorKind.REVIEWER)
        session.add(structure); session.flush(); structure_id = structure.id
        other = session.scalar(select(Paper).where(Paper.id != f.paper_id))
        other_task = ReviewTask(paper_id=other.id, created_by_id=f.admin_id,
            assigned_reviewer_id=f.reviewer_id, status='assigned', version=1)
        session.add(other_task); session.flush()
        other_workspace = PaperWorkspace(paper_id=other.id, review_task_id=other_task.id,
            state='editing', version=1)
        session.add(other_workspace); session.flush()
        other_compound = Compound(paper_id=other.id, workspace_id=other_workspace.id,
            compound_label='1', sort_order=0, created_by_kind=ChangeActorKind.REVIEWER)
        session.add(other_compound); session.flush()
        session.add(Structure(paper_id=other.id, workspace_id=other_workspace.id,
            compound_id=other_compound.id, input_method=StructureInputMethod.MANUAL_SMILES,
            smiles='C', canonical_smiles='C', status=StructureStatus.DRAFT,
            depiction_asset_id=asset_id, created_by_kind=ChangeActorKind.REVIEWER))
    headers={'X-CSRF-Token':f.login('workspace.admin')}
    assert remove(f,headers=headers).status_code == 200
    assert f.client.get(f'/api/v1/assets/{asset_id}').status_code == 200
    response=f.client.get(f'/api/v1/admin/files/{asset_id}/references')
    assert response.status_code == 200,response.text
    assert all(row['id'] != str(structure_id) for row in response.json()['references'])


def test_active_legacy_delivery_is_rejected_without_waiting_for_its_run_lock(workspace_fixture):
    from concurrent.futures import ThreadPoolExecutor
    from app.ai_prefill.service import AiPrefillService
    from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
    from app.api.errors import APIError
    from app.papers.removal import RemovePaperRequest, remove_paper
    from sqlalchemy import text
    f = workspace_fixture
    with f.session_factory.begin() as session:
        run = AiPrefillService().queue(session,workspace_id=f.workspace_id,
            requested_by_id=f.admin_id,engine='synthetic',engine_version='1').run
        run.status = AiExtractionRunStatus.RUNNING
        run_id = run.id
    def attempt():
        with f.session_factory.begin() as session:
            session.execute(text("SET LOCAL lock_timeout = '750ms'"))
            try:
                remove_paper(session,paper_id=f.paper_id,actor_id=f.admin_id,
                    payload=RemovePaperRequest(**removal_body(f)),request_id='concurrent-test',ip_address='127.0.0.1')
            except APIError as error:
                return error.code
    with f.session_factory.begin() as delivering:
        delivering.scalar(select(AiExtractionRun).where(AiExtractionRun.id==run_id).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(attempt).result(timeout=5) == 'PAPER_TASK_ACTIVE'
