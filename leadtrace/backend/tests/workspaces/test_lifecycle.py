from pathlib import Path
import hashlib
import json
import pytest
from sqlalchemy import select
from app.users.models import User
from app.workspaces.models import PaperWorkspace, ReviewTask, ReviewTaskState, WorkspaceState
from app.workspaces.service import WorkspaceService, WorkspaceNotFoundError
from app.workspaces.assignment import AssignmentService
from app.workspaces.lifecycle import recall_assignment, archive_reset, ensure_admin_workspace, LifecycleConflict
from tests.ai_prefill.test_apply import create_ai_context


def test_recall_revokes_access_and_reassigns_same_draft(auth_session_factory):
    ctx = create_ai_context(auth_session_factory)
    with auth_session_factory.begin() as session:
        ws = session.get(PaperWorkspace, ctx.workspace_id)
        ws.version = 17
        recall_assignment(session, paper_id=ctx.paper_id, admin_id=ctx.admin_id,
                          expected_workspace_id=ctx.workspace_id,expected_workspace_version=17, expected_task_version=1)
        assert ws.version == 17
        task = session.get(ReviewTask, ws.review_task_id)
        assert task.assigned_reviewer_id is None and task.status == ReviewTaskState.UNASSIGNED
        with pytest.raises(WorkspaceNotFoundError):
            WorkspaceService().get_workspace(session, workspace_id=ws.id, actor=session.get(User, ctx.reviewer_id))
        assigned = AssignmentService().assign(session,paper_id=ctx.paper_id,reviewer_id=ctx.reviewer_id,
            admin_id=ctx.admin_id,request_id='test',ip_address='127.0.0.1')
        assert assigned.workspace.id == ctx.workspace_id and assigned.workspace.version == 17
        assert assigned.task.version == 3


def test_reset_exports_then_creates_distinct_blank_workspace(auth_session_factory, tmp_path):
    ctx = create_ai_context(auth_session_factory)
    with auth_session_factory.begin() as session:
        old = session.get(PaperWorkspace, ctx.workspace_id)
        new, archive = archive_reset(session,paper_id=ctx.paper_id,admin_id=ctx.admin_id,
            expected_workspace_id=ctx.workspace_id,expected_workspace_version=1,expected_task_version=1,confirm_paper_key='LT-JMC-2024-67-05-AI1',
            archive_root=tmp_path/'archives',asset_root=tmp_path/'assets')
        assert new.id != old.id and new.version == 1
        assert old.state == WorkspaceState.ARCHIVED and old.version == 1
        assert session.get(ReviewTask,new.review_task_id).status == ReviewTaskState.UNASSIGNED
        directory = tmp_path/'archives'/archive.relative_path
        manifest = json.loads((directory/'manifest.json').read_text())
        for item in manifest['files']:
            assert hashlib.sha256((directory/item['path']).read_bytes()).hexdigest() == item['sha256']
        assert json.loads((directory/'workspace.json').read_text())['workspace']['id'] == str(old.id)
        assert ensure_admin_workspace(session,ctx.paper_id,ctx.admin_id).id == new.id


def test_reset_wrong_confirmation_and_export_failure_do_not_retire(auth_session_factory,tmp_path):
    ctx = create_ai_context(auth_session_factory)
    with auth_session_factory.begin() as session:
        kwargs=dict(paper_id=ctx.paper_id,admin_id=ctx.admin_id,expected_workspace_id=ctx.workspace_id,expected_workspace_version=1,
                    expected_task_version=1,archive_root=tmp_path/'bad',asset_root=tmp_path/'assets')
        with pytest.raises(LifecycleConflict):archive_reset(session,confirm_paper_key='wrong',**kwargs)
        (tmp_path/'bad').write_text('not a directory')
        with pytest.raises(OSError):archive_reset(session,confirm_paper_key='LT-JMC-2024-67-05-AI1',**kwargs)
        old=session.get(PaperWorkspace,ctx.workspace_id)
        assert old.state == WorkspaceState.EDITING
        assert session.get(ReviewTask,old.review_task_id).assigned_reviewer_id == ctx.reviewer_id


def test_recall_rejects_pending_submission(auth_session_factory):
    ctx = create_ai_context(auth_session_factory)
    with auth_session_factory.begin() as session:
        ws=session.get(PaperWorkspace,ctx.workspace_id)
        ws.state=WorkspaceState.SUBMITTED
        session.get(ReviewTask,ws.review_task_id).status=ReviewTaskState.SUBMITTED
        with pytest.raises(LifecycleConflict,match='submission'):
            recall_assignment(session,paper_id=ctx.paper_id,admin_id=ctx.admin_id,
                              expected_workspace_id=ctx.workspace_id,expected_workspace_version=1,expected_task_version=1)


def test_archive_restores_known_catalog_metadata_and_copies_assets(auth_session_factory,tmp_path):
    from app.assets.models import Asset,AssetCategory,AssetAccessLevel,AssetIntegrityState
    from app.papers.models import Paper
    from app.workspaces.models import ChangeEvent,ChangeActorKind
    ctx=create_ai_context(auth_session_factory)
    root=tmp_path/'assets';root.mkdir()
    (root/'synthetic.svg').write_bytes(b'<svg/>')
    with auth_session_factory.begin() as session:
        paper=session.get(Paper,ctx.paper_id);old_title=paper.title;paper.title='Human updated title'
        asset=Asset(storage_key='managed/synthetic.svg',original_filename='synthetic.svg',sha256=hashlib.sha256(b'<svg/>').hexdigest(),
            byte_size=6,mime_type='image/svg+xml',category=AssetCategory.RDKIT_STRUCTURE,access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,source_metadata={},derivation_metadata={})
        session.add(asset);session.flush()
        session.add(ChangeEvent(paper_id=paper.id,workspace_id=ctx.workspace_id,entity_type='paper',entity_id=paper.id,
            action='bibliography.update',before_value={'title':old_title},after_value={'title':paper.title,'asset_id':str(asset.id)},
            actor_kind=ChangeActorKind.ADMIN,actor_id=ctx.admin_id))
        session.flush()
        new,archive=archive_reset(session,paper_id=ctx.paper_id,admin_id=ctx.admin_id,expected_workspace_id=ctx.workspace_id,expected_workspace_version=1,
            expected_task_version=1,confirm_paper_key=paper.paper_key,archive_root=tmp_path/'archives',asset_root=root)
        assert paper.title==old_title
        folder=tmp_path/'archives'/archive.relative_path
        export=json.loads((folder/'workspace.json').read_text())
        assert export['snapshot']['paper']['title']=='Human updated title'
        assert (folder/'assets'/str(asset.id)/'synthetic.svg').read_bytes()==b'<svg/>'


def test_archive_missing_linked_asset_blocks_reset(auth_session_factory,tmp_path):
    from app.assets.models import Asset,AssetCategory,AssetAccessLevel,AssetIntegrityState
    from app.workspaces.models import ChangeEvent,ChangeActorKind
    ctx=create_ai_context(auth_session_factory)
    with auth_session_factory.begin() as session:
        asset=Asset(storage_key='managed/missing.svg',original_filename='missing.svg',sha256='a'*64,byte_size=6,
            mime_type='image/svg+xml',category=AssetCategory.RDKIT_STRUCTURE,access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,source_metadata={},derivation_metadata={})
        session.add(asset);session.flush()
        session.add(ChangeEvent(paper_id=ctx.paper_id,workspace_id=ctx.workspace_id,entity_type='asset',entity_id=asset.id,
            action='test',before_value=None,after_value={'asset_id':str(asset.id)},actor_kind=ChangeActorKind.ADMIN,actor_id=ctx.admin_id))
        session.flush()
        with pytest.raises(FileNotFoundError):
            archive_reset(session,paper_id=ctx.paper_id,admin_id=ctx.admin_id,expected_workspace_id=ctx.workspace_id,expected_workspace_version=1,
                expected_task_version=1,confirm_paper_key='LT-JMC-2024-67-05-AI1',archive_root=tmp_path/'archives',asset_root=tmp_path/'assets')
        assert session.get(PaperWorkspace,ctx.workspace_id).state==WorkspaceState.EDITING
        assert not list((tmp_path/'archives').glob('*/*'))


def test_lifecycle_api_permissions_versions_and_stale_reviewer(workspace_fixture):
    fixture=workspace_fixture
    endpoint=f'/api/v2/admin/papers/{fixture.paper_id}'
    fixture.login('workspace.reviewer')
    assert fixture.client.get(endpoint+'/management').status_code==403
    token=fixture.login('workspace.admin')
    management=fixture.client.get(endpoint+'/management')
    assert management.status_code==200
    state=management.json()
    payload={'expected_workspace_id':state['workspace_id'],'expected_workspace_version':state['workspace_version'],'expected_task_version':state['task_version']}
    assert fixture.client.post(endpoint+'/recall',json=payload).status_code==403
    assert fixture.client.post(endpoint+'/recall',json={**payload,'expected_task_version':99},headers={'X-CSRF-Token':token}).status_code==409
    response=fixture.client.post(endpoint+'/recall',json=payload,headers={'X-CSRF-Token':token})
    assert response.status_code==200,response.text
    assert response.json()['assignment_state']=='unassigned'
    assert response.json()['workspace_version']==state['workspace_version']
    catalog=fixture.client.get(endpoint).json()
    assert catalog['review']['assigned_reviewer_id'] is None
    assert catalog['review']['submission_state']=='not_submitted'
    token=fixture.login('workspace.reviewer')
    assert fixture.client.get(f'/api/v2/workspaces/{fixture.workspace_id}').status_code==404
    assert fixture.client.get(f'/api/v2/papers/{fixture.paper_id}/source-pdf').status_code==404
    assert fixture.client.patch(f'/api/v2/workspaces/{fixture.workspace_id}/bibliography',json={
        'expected_workspace_version':state['workspace_version'],'title':'stale tab'},headers={'X-CSRF-Token':token}).status_code==404


def test_archive_copies_completed_console_job_and_blocks_running_job(auth_session_factory,tmp_path):
    from tests.ai_tasks.test_queue import seed
    from app.ai_tasks.models import AiTask
    ctx=seed(auth_session_factory,1)
    with auth_session_factory.begin() as session:
        job=session.scalar(select(AiTask));job.state='running';session.flush()
        arguments=dict(paper_id=ctx.paper_id,admin_id=ctx.admin_id,expected_workspace_id=ctx.workspace_id,expected_workspace_version=1,
            expected_task_version=1,confirm_paper_key='LT-JMC-2024-67-05-AI1',archive_root=tmp_path/'archives',asset_root=tmp_path/'assets',task_root=tmp_path/'tasks')
        with pytest.raises(LifecycleConflict,match='running AI task'):archive_reset(session,**arguments)
        job.state='completed';session.flush()
        job_dir=tmp_path/'tasks'/str(job.id);job_dir.mkdir(parents=True)
        (job_dir/'report.json').write_text('{"synthetic":true}')
        _,archive=archive_reset(session,**arguments)
        assert (tmp_path/'archives'/archive.relative_path/'ai-tasks'/str(job.id)/'report.json').read_text()=='{"synthetic":true}'
        assert job_dir.exists()
