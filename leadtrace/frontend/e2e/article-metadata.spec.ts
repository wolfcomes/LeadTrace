import { expect,test } from '@playwright/test';
import { adminSubmissionDetail,publicationIds } from '../tests/paper-publication-v2-fixtures';

test('article metadata comparison preserves target roles, sources and collapsed unchanged groups',async({page})=>{
  const detail=structuredClone(adminSubmissionDetail) as any;
  detail.submission.reviewer_note='管理员补充书目信息，新增内容待审核。';
  const before=structuredClone(detail.submission.snapshot);
  const profile={molecular_forms:[{label:'Macrocycle',source:'Page 2'}],targets:[{name:'Target A',role:'primary',organism:'Homo sapiens',gene_symbol:'GENEA',source:'Page 1'}],optimization_goals:[{label:'Potency',source:'Abstract'}]};
  before.paper.research_profile=structuredClone(profile);
  const current=detail.submission.snapshot.paper;
  Object.assign(current,{pmid:'12345678',abstract:'Synthetic original abstract.',abstract_source:'Page 1, Abstract',abstract_status:'extracted',research_profile:structuredClone(profile)});
  current.research_profile.optimization_goals[0]={label:'Brain penetration',source:'Page 3'};
  detail.comparison={kind:'previous_submission',baseline_submission_number:1,baseline_snapshot:before,events:[],warnings:[]};
  const writes:string[]=[];
  await page.route(/\/api\/v[12]\//,async route=>{
    const path=new URL(route.request().url()).pathname;
    if(!['GET','HEAD'].includes(route.request().method()))writes.push(path);
    if(path==='/api/v1/auth/session')return route.fulfill({json:{user:{username:'admin',display_name:'Test Admin',role:'admin',must_change_password:false},csrf_token:'synthetic'}});
    if(path===`/api/v2/admin/submissions/${publicationIds.submission}`)return route.fulfill({json:detail});
    return route.fulfill({status:404,json:{code:'NOT_FOUND'}});
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(`/admin/submissions/${publicationIds.submission}`);
  await expect(page.locator('.reviewer-attestation strong')).toHaveText('提交说明');
  await page.locator('[data-record-tab="article"]').click();
  const after=page.locator('[data-record-side="after"]');
  await expect(after).toContainText('12345678');
  await expect(after).toContainText('Synthetic original abstract.');
  await expect(after.locator('[data-profile-diff-group="optimization_goals"]')).toHaveAttribute('open');
  await expect(after.locator('[data-profile-diff-group="targets"]')).not.toHaveAttribute('open');
  await expect(after.locator('[data-profile-diff-group="molecular_forms"]')).toHaveCount(0);
  await expect(after.locator('[data-profile-diff-group="optimization_goals"]')).toContainText('Brain penetration');
  await after.locator('[data-profile-diff-group="targets"] > summary').click();
  await expect(after.locator('[data-profile-group="targets"]')).toContainText('主要靶点');
  await expect(after.locator('[data-profile-group="targets"]')).toContainText('Homo sapiens');
  await page.screenshot({path:'test-results/article-metadata-approval.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  expect(writes).toEqual([]);
});

test('reviewer article cards and fixed modalities fit mobile with a long title and preserve legacy data',async({page})=>{
  const id=(n:number)=>`92000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
  const paper=id(1),wid=id(2);
  let ws:any={id:wid,review_task_id:id(3),assigned_reviewer_id:id(4),state:'editing',version:1,task_status:'assigned',bibliography:{paper_id:paper,paper_key:'SYNTHETIC-ARTICLE',title:'Synthetic '+ 'UnbrokenScientificTitle'.repeat(8)+' article profile',journal:'UI test',publication_year:2026,volume:'1',issue:'1',doi:null,abstract:'Original source abstract.',abstract_source:'Europe PMC routine provenance',abstract_status:'extracted',abstract_note:'Routine check note',research_profile:{molecular_forms:[{label:'Legacy macrocycle',source:'Page 1'}],modalities:[{label:'直接靶点调节',source:'Page 2'},{label:'小分子抑制剂',source:'Page 2'},{label:'大环类',source:'Page 2'}],targets:[{name:'Comparator',role:'selectivity',source:'Table 2'},{name:'Main target',role:'primary',organism:'Homo sapiens',gene_symbol:'GENE',source:'Page 3',review_hint:'Confirm species',evidence:[{source_kind:'main_pdf',quoted_text:'Exact source sentence for the main target.',page_number:3}]}]}},source:{asset_id:id(5),source_root_key:'source_pdfs',source_key:'synthetic.pdf',sha256:'a'.repeat(64),page_count:5},sections:['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}))};
  const writes:any[]=[];
  await page.route('**/api/v*/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/v1/auth/session')return route.fulfill({json:{user:{username:'reviewer',display_name:'Test reviewer',role:'reviewer',must_change_password:false},csrf_token:'synthetic'}});
    if(path.endsWith('/review-progress'))return route.fulfill({json:{workspace_id:wid,workspace_version:ws.version,tracking_started:false,items:[],sections:[]}});
    if(path.endsWith('/bibliography')&&route.request().method()==='PATCH'){
      const {expected_workspace_version,...fields}=route.request().postDataJSON();writes.push(fields);ws={...ws,version:expected_workspace_version+1,bibliography:{...ws.bibliography,...fields}};return route.fulfill({json:ws});
    }
    if(path===`/api/v2/workspaces/${wid}`)return route.fulfill({json:ws});
    return route.fulfill({status:404,json:{code:'NOT_FOUND'}});
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(`/review/papers/${paper}?workspace=${wid}&tab=bibliography`);
  await expect(page.locator('[data-article-abstract]')).toHaveText('Original source abstract.');
  await expect(page.locator('[data-target-card] strong').first()).toHaveText('Main target');
  await expect(page.getByText('Routine check note',{exact:true})).toHaveCount(0);
  await expect(page.getByText('Europe PMC routine provenance',{exact:true})).toHaveCount(0);
  await expect(page.locator('[data-target-evidence]').first()).not.toHaveAttribute('open');
  await expect(page.locator('[data-article-module]')).toHaveCount(6);
  await expect(page.locator('[data-article-module=modalities] h3')).toContainText('分子类型');
  await expect(page.locator('[data-modality-group=primary]')).toContainText('小分子抑制剂');
  await expect(page.locator('[data-modality-group=supplementary]')).toContainText('大环类');
  await expect(page.locator('[data-modality-group=legacy]')).toContainText('直接靶点调节');
  await expect(page.locator('[data-modality-group] [data-term-evidence][open]')).toHaveCount(0);
  const moduleBoxes=await page.locator('[data-article-module]').evaluateAll(nodes=>nodes.map(node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,h:r.height};}));
  expect(moduleBoxes[0]!.y).toBe(moduleBoxes[1]!.y);expect(moduleBoxes[1]!.x).toBeGreaterThan(moduleBoxes[0]!.x);expect(moduleBoxes[0]!.h).toBe(220);expect(moduleBoxes[2]!.h).toBe(320);
  await page.locator('[data-target-evidence] > summary').first().click();
  await expect(page.locator('[data-target-card]').first().locator('blockquote')).toHaveText('Exact source sentence for the main target.');
  await expect(page.locator('[data-target-card]').first().locator('[data-article-source-link]')).toHaveAttribute('href',new RegExp('#page=3$'));
  await page.screenshot({path:'test-results/article-reviewer-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  await page.locator('[data-edit-bibliography]').click();
  await expect(page.locator('[data-edit-group="molecular_forms"]')).toHaveCount(0);
  await page.locator('[data-edit-group="modalities"] > summary').click();
  await expect(page.locator('[data-modality-choice]')).toHaveCount(15);
  await expect(page.locator('[data-modality-choice-group=primary] input')).toHaveCount(10);
  await expect(page.locator('[data-modality-choice-group=supplementary] input')).toHaveCount(5);
  await page.locator('[data-modality-choice][value="PROTAC"]').check();
  await page.locator('[data-edit-group="modalities"] > summary').click();
  await page.locator('[data-save-bibliography]').click();
  await expect(page.locator('[data-edit-group="modalities"]')).toHaveAttribute('open');
  await expect(page.locator('[data-term-source]').last()).toBeFocused();
  expect(writes).toHaveLength(0);
  await page.locator('[data-term-source]').last().fill('Synthetic source, page 4');
  await page.screenshot({path:'test-results/article-reviewer-editor-mobile.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  await page.locator('[data-save-bibliography]').click();
  await expect.poll(()=>writes.length).toBe(1);
  expect(writes[0].research_profile.molecular_forms).toEqual([{label:'Legacy macrocycle',source:'Page 1'}]);
  expect(writes[0].research_profile.modalities.slice(0,3)).toEqual([{label:'直接靶点调节',source:'Page 2'},{label:'小分子抑制剂',source:'Page 2'},{label:'大环类',source:'Page 2'}]);
  expect(writes[0].abstract_note).toBe('Routine check note');
  expect(writes[0].research_profile.targets[1].evidence[0].quoted_text).toBe('Exact source sentence for the main target.');
});

test('approval aligns asymmetric quotation rows and synchronizes profile and PDB scrolling',async({page})=>{
  const detail=structuredClone(adminSubmissionDetail) as any;
  const before=structuredClone(detail.submission.snapshot);
  const quote=(text:string)=>[{source_kind:'main_pdf',quoted_text:text,page_number:1}];
  before.paper.research_profile={mechanisms:Array.from({length:5},(_,i)=>({label:`Mechanism ${i}`,source:'Existing explanation',evidence:quote('Short quotation.')}))};
  before.paper.pdb_references=Array.from({length:5},(_,i)=>({pdb_id:`${i+1}ABC`,usage:'cited_structure',source_context:'Existing context',evidence:quote('Short structure quotation.')}));
  detail.submission.snapshot.paper.research_profile=structuredClone(before.paper.research_profile);
  detail.submission.snapshot.paper.pdb_references=structuredClone(before.paper.pdb_references);
  delete before.paper.abstract;delete before.paper.pmid;
  detail.submission.snapshot.paper.pmid='12345678';
  detail.submission.snapshot.paper.abstract='A substantially longer abstract above the research profile. '.repeat(30);
  for(const entry of detail.submission.snapshot.paper.research_profile.mechanisms)entry.evidence=quote('Long original quotation for comparison alignment. '.repeat(35));
  for(const entry of detail.submission.snapshot.paper.pdb_references)entry.evidence=quote('Long original structure quotation. '.repeat(40));
  detail.comparison={kind:'previous_submission',baseline_submission_number:1,baseline_snapshot:before,events:[],warnings:[]};
  await page.route('**/api/v*/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/v1/auth/session')return route.fulfill({json:{user:{username:'admin',display_name:'Test Admin',role:'admin',must_change_password:false},csrf_token:'synthetic'}});
    if(path===`/api/v2/admin/submissions/${publicationIds.submission}`)return route.fulfill({json:detail});
    return route.fulfill({status:404,json:{code:'NOT_FOUND'}});
  });
  await page.setViewportSize({width:1600,height:1000});
  await page.goto(`/admin/submissions/${publicationIds.submission}`);
  await page.locator('[data-record-tab=article]').click();
  for(const key of ['mechanisms:0','mechanisms:1','pdb:0','pdb:1']) {
    const pair=page.locator(`[data-profile-pair="${key}"]`);
    await expect(pair).toHaveCount(2);
    await expect.poll(async()=>pair.evaluateAll(nodes=>Math.abs(nodes[0]!.getBoundingClientRect().height-nodes[1]!.getBoundingClientRect().height))).toBeLessThan(2);
    await expect.poll(async()=>pair.evaluateAll(nodes=>Math.abs(nodes[0]!.getBoundingClientRect().y-nodes[1]!.getBoundingClientRect().y))).toBeLessThan(2);
  }
  for(const selector of ['[data-profile-scroll=mechanisms]','[data-pdb-scroll]']) {
    const left=page.locator(`[data-record-side=before] ${selector}`),right=page.locator(`[data-record-side=after] ${selector}`);
    await expect(left).toHaveAttribute('tabindex','0');
    await expect(left).toHaveAttribute('aria-label',/.+/);
    await right.evaluate(node=>{node.scrollTop=180;node.dispatchEvent(new Event('scroll'));});
    await expect.poll(()=>left.evaluate(node=>node.scrollTop)).toBe(180);
    await left.evaluate(node=>{node.scrollTop=80;node.dispatchEvent(new Event('scroll'));});
    await expect.poll(()=>right.evaluate(node=>node.scrollTop)).toBe(80);
  }
});
