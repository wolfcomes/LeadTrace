def test_provenance_authorization_versions_and_snapshot_freezing(workspace_fixture):
    from app.workspaces.snapshot import build_paper_snapshot
    f=workspace_fixture
    read=f'/api/v2/workspaces/{f.workspace_id}/ai-provenance'
    write=f'/api/v2/admin/workspaces/{f.workspace_id}/ai-provenance'
    record=dict(run_key='api-run',stage='prefill',model='gpt-test',reasoning_effort='high',adapter='codex',
                verification='requested_only',source_sha256='a'*64,candidate_file_sha256='b'*64,
                applied_workspace_version=1,outcome='completed')
    payload={'expected_workspace_version':1,'record':record}
    assert f.client.get(read).status_code==401
    csrf=f.login('workspace.reviewer')
    assert f.client.get(read).json()['items']==[]
    assert f.client.post(write,json=payload,headers={'X-CSRF-Token':csrf}).status_code==403
    f.login('workspace.other')
    assert f.client.get(read).status_code==404
    csrf=f.login('workspace.admin')
    assert f.client.post(write,json=payload).status_code==403
    with f.session_factory() as session:
        frozen=build_paper_snapshot(session,f.workspace_id)
    response=f.client.post(write,json=payload,headers={'X-CSRF-Token':csrf})
    assert response.status_code==200, response.text
    assert response.json()['created'] is True
    assert response.json()['workspace_version']==1
    assert f.client.post(write,json=payload,headers={'X-CSRF-Token':csrf}).json()['created'] is False
    assert 'ai_provenance' not in frozen
    detail=f.client.get(f'/api/v2/workspaces/{f.workspace_id}').json()
    assert detail['ai_provenance'][0]['model']=='gpt-test'
    payload['expected_workspace_version']=2
    assert f.client.post(write,json=payload,headers={'X-CSRF-Token':csrf}).status_code==409
    payload['expected_workspace_version']=1
    payload['record']['source_sha256']='c'*64
    assert f.client.post(write,json=payload,headers={'X-CSRF-Token':csrf}).status_code==409
    f.login('workspace.reviewer')
    assert f.client.get('/api/v2/review/tasks').json()['items'][0]['ai_provenance'][0]['model']=='gpt-test'
