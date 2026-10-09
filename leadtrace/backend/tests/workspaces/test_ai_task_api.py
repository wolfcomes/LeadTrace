from uuid import uuid4


def test_admin_queue_permissions_csrf_idempotency_and_cancel(workspace_fixture,monkeypatch,tmp_path):
    f=workspace_fixture;settings=f.client.app.state.settings
    settings.ai_task_worker_enabled=True;settings.ai_task_root=tmp_path/'jobs'
    settings.ai_task_presets=[{'id':'synthetic','label':'Test','adapter':'codex','model':'gpt-test','efforts':['high'],'default_effort':'high'}]
    monkeypatch.setattr('app.ai_tasks.service.shutil.which',lambda _: '/bin/synthetic')
    url=f'/api/v2/admin/papers/{f.paper_id}/ai-tasks'
    assert f.client.get('/api/v2/admin/ai-tasks').status_code==401
    f.login('workspace.reviewer')
    assert f.client.get('/api/v2/admin/ai-tasks').status_code==403
    token=f.login('workspace.admin');headers={'X-CSRF-Token':token}
    options=f.client.get('/api/v2/admin/ai-tasks/options').json()
    assert options['settings']['max_concurrent']==4
    body={'action':'prefill','preset_id':'synthetic','reasoning_effort':'high','expected_workspace_id':str(f.workspace_id),'expected_task_version':1,'expected_workspace_version':1,'idempotency_key':str(uuid4())}
    assert f.client.post(url,json=body).status_code==403
    response=f.client.post(url,json=body,headers=headers)
    assert response.status_code==200,response.text
    job=response.json();assert job['state']=='queued'
    assert f.client.post(url,json=body,headers=headers).json()['id']==job['id']
    conflict=f.client.post(url,json={**body,'idempotency_key':str(uuid4())},headers=headers)
    assert conflict.status_code==409
    assert f.client.put('/api/v2/admin/ai-tasks/settings',json={'max_concurrent':0},headers=headers).status_code==422
    assert f.client.put('/api/v2/admin/ai-tasks/settings',json={'max_concurrent':3},headers=headers).json()=={'max_concurrent':3}
    cancelled=f.client.post(f"/api/v2/admin/ai-tasks/{job['id']}/cancel",headers=headers).json()
    assert cancelled['state']=='cancelled'
    assert f.client.get(f"/api/v2/admin/ai-tasks/{job['id']}/report").status_code==409
    retried=f.client.post(f"/api/v2/admin/ai-tasks/{job['id']}/retry",headers=headers,json={'idempotency_key':str(uuid4())})
    assert retried.status_code==200 and retried.json()['attempt']==2
    assert retried.json()['parent_job_id']==job['id']
    legacy=f.client.post(f'/api/v2/admin/papers/{f.paper_id}/ai-prefill',headers=headers)
    assert legacy.status_code==409
    assert 'Admin AI task console' in legacy.text
    settings.ai_task_worker_enabled=False


def test_admin_can_read_saved_producer_report_without_exposing_it_to_reviewers(workspace_fixture,monkeypatch,tmp_path):
    from app.ai_tasks.models import AiTask
    f=workspace_fixture;settings=f.client.app.state.settings
    settings.ai_task_worker_enabled=True;settings.ai_task_root=tmp_path/'jobs'
    settings.ai_task_presets=[{'id':'synthetic','label':'Test','adapter':'codex','model':'gpt-test','efforts':['high'],'default_effort':'high'}]
    monkeypatch.setattr('app.ai_tasks.service.shutil.which',lambda _: '/bin/synthetic')
    token=f.login('workspace.admin')
    body={'action':'prefill','preset_id':'synthetic','reasoning_effort':'high','expected_workspace_id':str(f.workspace_id),'expected_task_version':1,'expected_workspace_version':1,'idempotency_key':str(uuid4())}
    response=f.client.post(f'/api/v2/admin/papers/{f.paper_id}/ai-tasks',json=body,headers={'X-CSRF-Token':token})
    assert response.status_code==200
    from uuid import UUID
    identifier=UUID(response.json()['id']);url=f'/api/v2/admin/ai-tasks/{identifier}/report'
    assert f.client.get(url).status_code==409
    with f.session_factory.begin() as s:
        job=s.get(AiTask,identifier);job.state='needs_revision';job.delivery_state='applied'
        job.result_summary={'report_available':True,'applied_workspace_version':2,'producer_report':{'report_kind':'prefill','scientific_approval':False,'coverage':{'expected':2,'reviewed':1,'missing':[{'domain':'compound','ref':'missing'}]},'findings':[]}}
    response=f.client.get(url);assert response.status_code==200,response.text
    assert response.json()['report_kind']=='prefill' and response.json()['scientific_approval'] is False
    f.login('workspace.reviewer');assert f.client.get(url).status_code==403
    settings.ai_task_worker_enabled=False


def test_saved_delivery_action_requires_admin_csrf_and_is_idempotent(workspace_fixture,monkeypatch,tmp_path):
    from uuid import UUID
    from app.ai_tasks.models import AiTask
    f=workspace_fixture;settings=f.client.app.state.settings;settings.ai_task_worker_enabled=True;settings.ai_task_root=tmp_path/'jobs'
    settings.ai_task_presets=[{'id':'synthetic','label':'Test','adapter':'codex','model':'gpt-test','efforts':['high'],'default_effort':'high'}]
    monkeypatch.setattr('app.ai_tasks.service.shutil.which',lambda _: '/bin/synthetic')
    token=f.login('workspace.admin');headers={'X-CSRF-Token':token}
    body={'action':'prefill','preset_id':'synthetic','reasoning_effort':'high','expected_workspace_id':str(f.workspace_id),'expected_task_version':1,'expected_workspace_version':1,'idempotency_key':str(uuid4())}
    j=f.client.post(f'/api/v2/admin/papers/{f.paper_id}/ai-tasks',json=body,headers=headers).json();url=f"/api/v2/admin/ai-tasks/{j['id']}/deliver"
    assert f.client.post(url).status_code==403
    assert f.client.post(url,headers=headers).status_code==409
    with f.session_factory.begin() as s:
        job=s.get(AiTask,UUID(j['id']));job.state='completed';job.delivery_state='applied'
    # Replaying after a committed import succeeds without a second apply or files.
    response=f.client.post(url,headers=headers);assert response.status_code==200,response.text
    assert response.json()['delivery_state']=='applied' and response.json()['can_deliver'] is False
    assert f.client.post(url,headers=headers).status_code==200
    token=f.login('workspace.reviewer');assert f.client.post(url,headers={'X-CSRF-Token':token}).status_code==403
    settings.ai_task_worker_enabled=False


def test_repair_and_accept_require_admin_csrf_and_saved_review(workspace_fixture,monkeypatch,tmp_path):
    from uuid import UUID
    f=workspace_fixture;settings=f.client.app.state.settings
    settings.ai_task_worker_enabled=True;settings.ai_task_root=tmp_path/'jobs'
    settings.ai_task_presets=[{'id':'synthetic','label':'Test','adapter':'codex','model':'gpt-test','efforts':['high'],'default_effort':'high'}]
    monkeypatch.setattr('app.ai_tasks.service.shutil.which',lambda _: '/bin/synthetic')
    token=f.login('workspace.admin');headers={'X-CSRF-Token':token}
    body={'action':'prefill','preset_id':'synthetic','reasoning_effort':'high','expected_workspace_id':str(f.workspace_id),'expected_task_version':1,'expected_workspace_version':1,'idempotency_key':str(uuid4())}
    res=f.client.post(f'/api/v2/admin/papers/{f.paper_id}/ai-tasks',json=body,headers=headers);assert res.status_code==200
    jid=res.json()['id'];url=f'/api/v2/admin/ai-tasks/{jid}'
    repair={'preset_id':'synthetic','reasoning_effort':'high','idempotency_key':str(uuid4())}
    accept={'proposal_sha256':'a'*64}
    for endpoint,payload in [('repair',repair),('accept',accept)]:
        assert f.client.post(url+'/'+endpoint,json=payload).status_code==403
        r=f.client.post(url+'/'+endpoint,json=payload,headers=headers);assert r.status_code==409,r.text
    f.login('workspace.reviewer')
    assert f.client.post(url+'/repair',json=repair).status_code==403
    assert f.client.post(url+'/accept',json=accept).status_code==403
    settings.ai_task_worker_enabled=False
