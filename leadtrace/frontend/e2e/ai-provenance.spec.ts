import { expect, test } from '@playwright/test';
const id = (n: number) => `91000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
test('article model and effort survive language switch and do not imply current review', async ({ page }) => {
  const workspace=id(2),paper=id(1);
  const record={run_key:'synthetic',stage:'prefill',adapter:'codex',model:'gpt-test',reasoning_effort:'high',verification:'requested_only',outcome:'completed',source_sha256:'a'.repeat(64),candidate_file_sha256:'b'.repeat(64),applied_workspace_version:2};
  const sections=['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}));
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/preview/environment')return reply({},404);
    if(path.endsWith('/auth/session'))return reply({user:{username:'reviewer',display_name:'Reviewer',role:'reviewer',must_change_password:false},csrf_token:'test'});
    if(path===`/api/v2/workspaces/${workspace}`)return reply({id:workspace,review_task_id:id(3),assigned_reviewer_id:id(4),state:'editing',version:5,task_status:'assigned',ai_provenance:[record,{...record,run_key:'review',stage:'independent_review',model:'deepseek-flash',reasoning_effort:'max',applied_workspace_version:null,outcome:'needs_revision'}],bibliography:{paper_id:paper,paper_key:'SYNTHETIC',title:'Synthetic provenance example',journal:'Test',publication_year:2026,volume:'1',issue:'1',doi:null},source:{asset_id:id(6),source_root_key:'source_pdfs',source_key:'synthetic.pdf',sha256:'a'.repeat(64),page_count:1},sections});
    if(path.endsWith('/review-progress'))return reply({workspace_id:workspace,workspace_version:5,tracking_started:false,items:[],sections:sections.map(s=>({...s,total:0,viewed:0,complete:false}))});
    return reply({workspace_id:workspace,workspace_version:5,items:[],total:0});
  });
  await page.goto(`/review/papers/${paper}?workspace=${workspace}`);
  const card=page.locator('.ai-provenance');
  await expect(card).toContainText('gpt-test'); await expect(card).toContainText('high');
  await expect(card).toContainText('后续修改'); await expect(card).toContainText('独立复核');
  await page.locator('[data-language-switch]').selectOption('en');
  await expect(card).toContainText('Requested configuration only');
  await expect(card).toContainText('Independent review');
  await expect(card).toContainText('subsequent edits');
  await page.setViewportSize({width:390,height:844});
  await expect(card).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
