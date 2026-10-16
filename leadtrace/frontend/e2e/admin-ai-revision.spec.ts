import { expect, test } from '@playwright/test';

test('fresh directed revision uses current reviewer draft and auto-update workflow', async ({page}) => {
  const paper='92000000-0000-4000-8000-000000000001';
  const workspace='92000000-0000-4000-8000-000000000002';
  const job={id:'92000000-0000-4000-8000-000000000003',paper_id:paper,paper_key:'SYNTHETIC-REVISION',paper_title:'虚构示例：定向修订',workspace_id:workspace,workspace_version:2,action:'prefill',preset_id:'synthetic',model:'synthetic-model',reasoning_effort:'high',state:'completed',delivery_state:'applied',stage:'completed',error_code:null,error_message:null,created_at:'2026-10-16T00:00:00Z',started_at:null,finished_at:null,heartbeat_at:null,timeout_seconds:3600,attempt:1,parent_job_id:null,result_summary:{},can_revise:true,can_cancel:false,can_retry:false};
  let started:Record<string,unknown>|undefined;
  const unexpected:string[]=[];
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(!path.startsWith('/api/'))return route.continue();
    const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/preview/environment')return reply({},404);
    if(path.endsWith('/auth/session'))return reply({user:{username:'admin',display_name:'Admin',role:'admin',must_change_password:false},csrf_token:'synthetic'});
    if(path==='/api/v2/admin/ai-tasks')return reply({items:[job],total:1,settings:{max_concurrent:4},worker:{online:true,last_seen_at:null},presets:[{id:'synthetic',label:'示例模型',adapter:'codex',model:'synthetic-model',efforts:['high'],default_effort:'high',available:true,unavailable_reason:null}]});
    if(path.endsWith('/management'))return reply({paper_id:paper,paper_key:'SYNTHETIC-REVISION',workspace_id:workspace,workspace_version:9,task_version:4,assignment_state:'assigned',assigned_reviewer_id:'92000000-0000-4000-8000-000000000004',counts:{compounds:8,lineages:2},archives:[],archive_root:'/synthetic/archive'});
    if(path===`/api/v2/admin/papers/${paper}/ai-tasks`&&route.request().method()==='POST'){
      started=route.request().postDataJSON();return reply({...job,...started,state:'queued',delivery_state:'pending',can_revise:false,can_cancel:true});
    }
    unexpected.push(path);return reply({},404);
  });
  await page.goto('/admin/ai-tasks');
  await page.locator('[data-open-revision]').click();
  const dialog=page.getByRole('dialog');
  await expect(dialog).toContainText('目标版本 · 9');
  await expect(page.locator('[data-start-revision]')).toBeDisabled();
  await page.locator('[data-revision-instructions]').fill('按最新规则检查 Lineage 分图和枢纽分子。保留未受影响的人工修改与证据。');
  await expect(page.locator('[data-start-revision]')).toBeEnabled();
  if(process.env.LEADTRACE_REVISION_SCREENSHOT) {
    // Capture uses the bundled Chinese font on hosts without system CJK fonts.
    await page.addStyleTag({url:'/reviewer-guide/fonts.css'});
    await page.addStyleTag({content:'.ai-revision-dialog, .ai-revision-dialog * { font-family: "Noto Sans SC Variable", sans-serif !important; }'});
    await page.evaluate(()=>document.fonts.ready);
    await dialog.screenshot({path:process.env.LEADTRACE_REVISION_SCREENSHOT});
  }
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.locator('[data-start-revision]').click();
  await expect(dialog).toHaveCount(0);
  expect(started).toMatchObject({action:'revise',expected_workspace_id:workspace,expected_workspace_version:9,expected_task_version:4,preset_id:'synthetic',reasoning_effort:'high'});
  expect(started?.instructions).toContain('Lineage');
  await expect(page.locator('[data-accept-repair]')).toHaveCount(0);
  expect(unexpected).toEqual([]);
});
