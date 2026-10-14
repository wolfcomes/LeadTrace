import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { expect, test, type Page, type Locator } from '@playwright/test';
import { adminSubmissionDetail, publicationIds as ids, reviewerEvent } from '../tests/paper-publication-v2-fixtures';

const extra = (tail: string) => `50000000-0000-4000-8000-${tail.padStart(12,'0')}`;
function fixture() {
  const detail = structuredClone(adminSubmissionDetail) as any;
  const current = detail.submission.snapshot;
  current.structures[1].depiction_asset_id = extra('101');
  current.structure_source_images.push({...current.structure_source_images[0],id:extra('102'),compound_id:ids.compoundB,label:'Compound 18 structure',x0:'0.10',y0:'0.20',x1:'0.80',y1:'0.40'});
  const before = structuredClone(current);
  before.activities[0].value = '125';
  before.evidence[0].quoted_text = 'Original synthetic potency: 125 nM.';
  before.evidence[0].page_number = 3;
  before.structures[0].status = 'draft';
  before.structures[1].smiles = before.structures[1].canonical_smiles = 'CCO';
  before.structures[1].inchi = 'InChI=1S/C2H6O';
  before.structures[1].inchikey = 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N';
  before.structures[1].depiction_asset_id = ids.depictionA;
  current.compounds.push({...current.compounds[1],id:extra('103'),compound_label:'Compound 24',display_name:'Added series member',sort_order:2});
  current.structures.push({...current.structures[1],id:extra('104'),compound_id:extra('103')});
  current.lineage_members.push({...current.lineage_members[1],id:extra('105'),compound_id:extra('103'),sort_order:2});
  current.lineage_edges.push({...current.lineage_edges[0],id:extra('106'),parent_compound_id:ids.compoundB,child_compound_id:extra('103'),sort_order:1,modification_summary:'Added branch for comparison'});
  const event = (entity_type:string,entity_id:string,before_value:any,after_value:any,index:number) => ({...reviewerEvent,id:extra(String(200+index)),entity_type,entity_id,action:`${entity_type}.${before_value?'update':'create'}`,before_value,after_value});
  const events = [event('structure',ids.structureB,before.structures[1],current.structures[1],1),event('activity',ids.activity,before.activities[0],current.activities[0],2),event('evidence',ids.evidence,before.evidence[0],current.evidence[0],3),event('lineage_edge',extra('106'),null,current.lineage_edges[1],4)];
  detail.change_events=events;detail.reviewer_diff=events;
  detail.comparison={kind:'previous_submission',baseline_submission_number:1,baseline_snapshot:before,events,warnings:[]};
  return detail;
}
function syntheticPdf() {
  const python=process.env.LEADTRACE_PYTHON || '/data/home/zhangzhiyong/lead_optimization_collection/.worktrees/ai-prefill-tools/.venv/bin/python';
  return execFileSync(python,['-c',`import fitz,sys
p=fitz.open()
for n in range(4):
 s=p.new_page(width=600,height=800)
 s.draw_rect(fitz.Rect(60,160,480,320),fill=(0.85,0.95,0.88))
 s.insert_text((85,210),'Synthetic evidence - Compound 18',fontsize=15)
 s.insert_text((100,250),'IC50 = 12.5 nM',fontsize=20)
 s.draw_rect(fitz.Rect(90,330,450,680),color=(0.2,0.4,0.7),width=3)
sys.stdout.buffer.write(p.tobytes())`]);
}
async function setup(page:Page, body=fixture(), corruptPdf=false) {
  const writes:string[]=[], mutable:string[]=[], pdfRequests:string[]=[];
  const pdf=syntheticPdf();
  const sha=createHash('sha256').update(pdf).digest('hex');
  for(const snapshot of [body.submission.snapshot,body.comparison.baseline_snapshot]) {
    snapshot.source.sha256=sha;
    for(const item of [...snapshot.evidence,...snapshot.structure_source_images])item.source_sha256=sha;
  }
  await page.route(/\/api\/v[12]\//,async route=>{
    const path=new URL(route.request().url()).pathname;
    if(!['GET','HEAD'].includes(route.request().method()))writes.push(path);
    if(path.includes('/workspaces/')||path.includes('/layouts/')||path.includes('/source-images/'))mutable.push(path);
    if(path==='/api/v1/auth/session')return route.fulfill({json:{user:{username:'admin',display_name:'Test Admin',role:'admin',must_change_password:false},csrf_token:'synthetic'}});
    if(path===`/api/v2/admin/submissions/${ids.submission}`)return route.fulfill({json:body});
    if(path===`/api/v2/papers/${ids.paper}/source-pdf`){pdfRequests.push(path);return route.fulfill({contentType:'application/pdf',body:corruptPdf?Buffer.concat([pdf,Buffer.from('\n')]):pdf});}
    if(path.startsWith('/api/v1/assets/'))return route.fulfill({contentType:'image/svg+xml',body:`<svg xmlns="http://www.w3.org/2000/svg" width="300" height="140" viewBox="0 0 300 140"><path d="M50 95 L110 55 L170 95 L225 55" stroke="#183342" fill="none" stroke-width="3"/><text x="228" y="60" font-size="22" fill="#285da0">${path.includes(extra('101'))?'NH2':'OH'}</text></svg>`});
    return route.fulfill({status:404,json:{code:'NOT_FOUND',message:'Synthetic fixture only',details:{},request_id:'synthetic'}});
  });
  await page.goto(`/admin/submissions/${ids.submission}`);
  await expect(page.locator('[data-comparison-summary]')).toBeVisible();
  return {writes,mutable,pdfRequests};
}

async function expandEvidence(evidence: Locator) {
  const ancestors = evidence.locator('xpath=ancestor::details');
  for (let i=0; i<await ancestors.count(); i++) {
    const ancestor=ancestors.nth(i);
    if (!(await ancestor.evaluate(el => (el as HTMLDetailsElement).open))) await ancestor.locator(':scope > summary').click();
  }
  const content = evidence.locator(':scope > [data-disclosure]');
  if (!(await content.evaluate(el => (el as HTMLDetailsElement).open))) await content.locator(':scope > summary').click();
  const screenshot = evidence.locator('[data-evidence-image]');
  if (!(await screenshot.evaluate(el => (el as HTMLDetailsElement).open))) await screenshot.locator(':scope > summary').click();
}

test('changed records stay visible while unchanged details and screenshots expand on demand',async({page})=>{
  await page.setViewportSize({width:1536,height:1100});
  const requests=await setup(page);
  await page.locator('[data-record-tab="compounds"]').click();
  await page.locator(`[data-record-entry="${ids.compoundB}"]`).click();
  const before=page.locator('[data-record-side="before"]'),after=page.locator('[data-record-side="after"]');
  await expect(before).toContainText('Cell potency');await expect(after).toContainText('Human cells');
  await expect(before).toContainText('125');await expect(after).toContainText('12.5');
  await expect(page.locator('[data-evidence-thumbnail]')).toHaveCount(0);
  expect(requests.pdfRequests).toHaveLength(0);
  await expect(after.locator('.activity-context')).not.toBeVisible();
  await expect(after.locator(`[data-disclosure="section:identity:${ids.compoundB}"]`)).not.toHaveAttribute('open');
  await page.screenshot({path:'test-results/approval-records-compact.png',fullPage:true});
  await before.locator(`[data-disclosure="activity-context:${ids.activity}"] > summary`).click();
  await expect(after.locator('.activity-context')).toBeVisible();
  const firstEvidence=after.locator('[data-frozen-evidence]').first();
  await expandEvidence(firstEvidence);
  const crop=firstEvidence.locator('[data-evidence-thumbnail]');await expect(crop).toBeVisible();
  await expect.poll(()=>crop.evaluate((el:any)=>el.tagName==='CANVAS'?el.width:el.naturalWidth)).toBeGreaterThan(100);
  await expect.poll(()=>crop.evaluate((el:any)=> {
    if(el.tagName!=='CANVAS')return el.complete && el.naturalWidth>0;
    const pixels=el.getContext('2d').getImageData(0,0,el.width,el.height).data;
    for(let i=0;i<pixels.length;i+=4)if(pixels[i+3]>0 && pixels[i+1]>pixels[i]+10)return true;
    return false;
  })).toBe(true);
  const bounds=await crop.boundingBox();expect(bounds!.width/bounds!.height).toBeCloseTo(2.625,1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'test-results/approval-records-compound.png',fullPage:true});
  await after.locator('[data-enlarge-evidence]').first().click();
  const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
  await expect(dialog.locator('[data-evidence-thumbnail]')).toHaveAttribute('data-rendered','true');
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  await after.locator('[data-open-evidence-page]').first().click();
  await expect(dialog.locator('[data-evidence-thumbnail]')).toHaveAttribute('data-rendered','true');
  await expect(dialog.locator('.evidence-region-marker')).toBeVisible();
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  await expect(page.locator(`[data-record-entry="${ids.compoundA}"]`)).toHaveCount(0);
  await page.locator('[data-change-only]').uncheck();
  await expect(page.locator(`[data-record-entry="${ids.compoundA}"]`)).toBeVisible();
  await page.locator('[data-full-submission] > summary').click();
  const fullCrop=page.locator('[data-full-submission] [data-evidence-thumbnail]').first();
  await expandEvidence(page.locator('[data-full-submission] [data-frozen-evidence]').first());
  await expect(fullCrop).toHaveAttribute('data-rendered','true');
  expect(requests.pdfRequests).toHaveLength(1);
  expect(requests.writes).toEqual([]);expect(requests.mutable).toEqual([]);
});

test('whole lineage comparison shares layout and exposes changed relation with frozen evidence',async({page})=>{
  await page.setViewportSize({width:1536,height:1100});
  const requests=await setup(page);
  await page.locator('[data-record-tab="lineages"]').click();
  await page.locator(`[data-record-entry="${ids.lineage}"]`).click();
  const before=page.locator('[data-lineage-graph-side="before"]'),after=page.locator('[data-lineage-graph-side="after"]');
  await expect(before).toHaveAttribute('data-node-count','2');await expect(after).toHaveAttribute('data-node-count','3');
  await expect(before).toHaveAttribute('data-edge-count','1');await expect(after).toHaveAttribute('data-edge-count','2');
  await expect(before).toHaveAttribute('data-graph-presentation','points');
  await expect(after).toHaveAttribute('data-graph-presentation','points');
  await expect(page.locator('[data-graph-mode]')).toHaveCount(0);
  await expect(page.locator('[data-lineage-comparison] .frozen-compound-card')).toHaveCount(0);
  await expect(page.locator('[data-lineage-comparison] [data-rdkit-depiction]')).toHaveCount(0);
  await expect(page.locator('.lineage-change-navigation')).toContainText('3 处节点或关系变化');
  await page.locator('.lineage-entry-list > summary').click();
  await page.locator(`[data-lineage-relation][data-edge-id="${ids.edge}"]`).click();
  await expect(before).toHaveAttribute('data-selected-id',ids.edge);await expect(after).toHaveAttribute('data-selected-id',ids.edge);
  for(const side of ['before','after']) {
    const card=page.locator(`[data-record-side="${side}"]`);
    const relation=card.locator(`[data-disclosure="relation:${ids.edge}"]`),evidence=card.locator(`[data-disclosure="relation-evidence:${ids.edge}"]`);
    await expect(relation).not.toHaveAttribute('open');
    await expect(evidence).toHaveAttribute('open');
    expect((await evidence.boundingBox())!.y).toBeLessThan((await relation.boundingBox())!.y);
  }
  await expect(page.locator('[data-lineage-comparison]')).toContainText('Original synthetic potency');
  await expect(page.locator('[data-lineage-comparison]')).toContainText('Lead 1 was optimized');
  const initial=Number(await before.getAttribute('data-zoom'));
  await before.getByRole('button',{name:'放大',exact:true}).click();
  await expect.poll(async()=>Number(await before.getAttribute('data-zoom'))).toBeGreaterThan(initial);
  expect(await before.getAttribute('data-zoom')).toBe(await after.getAttribute('data-zoom'));
  await page.locator('[data-graph-sync]').uncheck();
  const frozenZoom=await after.getAttribute('data-zoom');
  await before.getByRole('button',{name:'放大',exact:true}).click();
  expect(await after.getAttribute('data-zoom')).toBe(frozenZoom);
  await page.locator('[data-graph-sync]').check();
  await page.locator('[data-change-next]').click();
  expect(await before.getAttribute('data-selected-id')).toBe(await after.getAttribute('data-selected-id'));
  await before.locator('[data-graph-fit]').click();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'test-results/approval-records-lineage.png',fullPage:true});
  await page.locator('[data-graph-expand]').click();
  await expect(page.locator('[data-lineage-comparison]')).toBeVisible();
  expect(requests.writes).toEqual([]);expect(requests.mutable).toEqual([]);
});

test('mobile record comparison stays within the screen and preserves full context',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await setup(page);
  await page.locator('[data-record-tab="compounds"]').click();
  await page.locator(`[data-record-entry="${ids.compoundB}"]`).click();
  await expect(page.locator('[data-record-side="after"]')).toContainText('Human cells');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  await page.screenshot({path:'test-results/approval-records-mobile.png',fullPage:true});
});


test('mismatching frozen PDF is explicit and never drawn as historical evidence',async({page})=>{
  await setup(page,fixture(),true);
  await page.locator('[data-record-tab="compounds"]').click();
  await page.locator(`[data-record-entry="${ids.compoundB}"]`).click();
  const side=page.locator('[data-record-side="after"]');
  await expandEvidence(side.locator('[data-frozen-evidence]').first());
  await expect(side.getByText('证据来源与冻结 PDF 不一致，请核对原文版本。').first()).toBeVisible();
  await expect(side.locator('[data-evidence-thumbnail]:visible')).toHaveCount(0);
});


test('later activities align when an earlier activity is removed on one side',async({page})=>{
  await page.setViewportSize({width:1536,height:1100});
  const body=fixture(),current=body.submission.snapshot,previous=body.comparison.baseline_snapshot;
  const second={...current.activities[0],id:extra('301'),assay_name:'Second assay',value:'42',sort_order:1};
  previous.activities.push(structuredClone(second));current.activities=[second];
  await setup(page,body);
  await page.locator('[data-record-tab="compounds"]').click();
  await page.locator(`[data-record-entry="${ids.compoundB}"]`).click();
  const row=(side:string)=>page.locator(`[data-record-side="${side}"] [data-activity-id="${second.id}"]`);
  await row('before').scrollIntoViewIfNeeded();
  await expect.poll(async()=>Math.abs((await row('before').boundingBox())!.y-(await row('after').boundingBox())!.y)).toBeLessThan(3);
  await expect(page.locator(`[data-record-side="after"] [data-activity-id="${ids.activity}"]`)).toContainText('本次提交已删除');
});

test('English record review preserves scientific values and translated controls',async({page})=>{
  await setup(page);
  await page.locator('[data-language-switch]').selectOption('en');
  await expect(page.locator('[data-record-tab="compounds"]')).toContainText('Compound');
  await expect(page.locator('[data-comparison-summary]')).toContainText('12.5');
  await expect(page.locator('[data-comparison-summary]')).not.toContainText('仅看有修改的条目');
  await page.locator('[data-record-tab="lineages"]').click();
  await expect(page.locator('[data-graph-expand]')).not.toContainText('放大对照');
  await expect(page.locator('[data-change-next]')).not.toContainText('下一处变化');
});


test('only changed fields lead both columns while unchanged content stays collapsed',async({page})=>{
  await page.setViewportSize({width:1536,height:1100});
  const body=fixture(),current=body.submission.snapshot,previous=body.comparison.baseline_snapshot;
  previous.structures=structuredClone(current.structures.slice(0,2));
  previous.activities[0]=structuredClone(current.activities[0]);
  const unchanged={...current.activities[0],id:extra('401'),assay_name:'Unchanged first assay',evidence_id:null,sort_order:-1};
  previous.activities.unshift(structuredClone(unchanged));current.activities.unshift(structuredClone(unchanged));
  current.compounds[1].description='New description';
  const requests=await setup(page,body);
  const before=page.locator('[data-record-side="before"]'),after=page.locator('[data-record-side="after"]');
  for(const side of [before,after]) {
    await expect(side.locator('.activity-result:visible')).toHaveCount(0);
    await expect(side.locator('[data-rdkit-depiction]:visible')).toHaveCount(0);
    await expect(side.locator('[data-review-fields] [data-field="source_context"]').first()).not.toBeVisible();
    await expect(side.locator('[data-review-fields] [data-field="display_name"]').first()).not.toBeVisible();
    await expect(side.locator(`[data-disclosure="activity:${ids.activity}"]`)).toHaveAttribute('open');
    const activity=side.locator(`[data-activity-id="${ids.activity}"]`),plain=side.locator(`[data-activity-id="${unchanged.id}"]`);
    expect((await activity.boundingBox())!.y).toBeLessThan((await plain.boundingBox())!.y);
    const active=side.locator('[data-section="activities"]'),structure=side.locator('[data-section="structures"]');
    expect((await active.boundingBox())!.y).toBeLessThan((await structure.boundingBox())!.y);
  }
  await expect(after.getByText('New description',{exact:true})).toBeVisible();
  const beforeY=(await before.locator('[data-section="activities"]').boundingBox())!.y;
  expect(Math.abs(beforeY-(await after.locator('[data-section="activities"]').boundingBox())!.y)).toBeLessThan(3);
  await expect(after.locator('[data-review-fields="evidence:'+ids.evidence+'"] [data-field="quoted_text"]')).toBeVisible();
  expect(requests.pdfRequests).toHaveLength(0);
  await page.screenshot({path:'test-results/approval-focus-fields.png',fullPage:true});
});


test('compound-only edits do not create lineage changes or node detail panels',async({page})=>{
  const body=fixture(),current=body.submission.snapshot;
  const before=structuredClone(current);
  before.compounds[1].description='Old compound description';
  before.activities[0].value='125';before.structures[1].canonical_smiles='CCO';
  before.structures[1].inchi='old identity';before.structures[1].inchikey='old key';
  body.comparison.baseline_snapshot=before;
  const requests=await setup(page,body);
  await page.locator('[data-record-tab="lineages"]').click();
  await expect(page.locator('[data-record-entry]')).toHaveCount(0);
  await expect(page.locator('[data-lineage-comparison]')).toHaveCount(0);
  await page.locator('[data-change-only]').uncheck();
  await page.locator('.lineage-entry-list > summary').click();
  await page.locator(`[data-lineage-member][data-compound-id="${ids.compoundB}"]`).click();
  await expect(page.locator('[data-node-membership]')).toContainText('节点未增删');
  await expect(page.locator('[data-lineage-comparison] .frozen-compound-card')).toHaveCount(0);
  await expect(page.locator('[data-lineage-comparison]')).not.toContainText('Cell potency');
  await expect(page.locator('[data-change-next]')).toBeDisabled();
  expect(requests.pdfRequests).toHaveLength(0);expect(requests.writes).toEqual([]);
});

test('one edited edge has one change label among many identical relationship types', async ({ page }) => {
  const body = fixture(), current = body.submission.snapshot;
  const root = current.compounds[0];
  current.compounds = [root, ...Array.from({ length: 8 }, (_, i) => ({
    ...current.compounds[1], id: extra(String(600 + i)), compound_label: `Node ${i + 1}`,
  }))];
  current.lineage_members = current.compounds.map((c: any, i: number) => ({
    ...current.lineage_members[0], id: extra(String(700 + i)), compound_id: c.id,
  }));
  current.lineage_edges = current.compounds.slice(1).map((c: any, i: number) => ({
    ...current.lineage_edges[0], id: extra(String(800 + i)),
    parent_compound_id: root.id, child_compound_id: c.id,
    modification_summary: 'Original relationship',
  }));
  current.edge_evidence_links = [];
  body.comparison.baseline_snapshot = structuredClone(current);
  current.lineage_edges[3].modification_summary = 'Only this relationship was corrected';
  const requests = await setup(page, body);
  await page.locator('[data-record-tab="lineages"]').click();
  const canvas = page.locator('[data-lineage-graph-side="after"] .frozen-graph-canvas');
  await expect.poll(() => canvas.evaluate((el: any) => el._cyreg?.cy?.edges().length)).toBe(8);
  const renderedEdges = (): Promise<Array<{ id: string; change: string; label: string; centerLabel: string }>> => canvas.evaluate((el: any) => el._cyreg.cy.edges().map((edge: any) => ({
    id: edge.id(), change: edge.data('change'), label: edge.style('target-label'),
    centerLabel: edge.style('label'),
  })));
  const edges = await renderedEdges();
  expect(edges.filter(e => e.change !== 'unchanged').map(e => e.id)).toEqual([extra('803')]);
  expect(edges.every(e => !e.centerLabel)).toBe(true);
  await page.screenshot({ path: 'test-results/approval-single-edge-label.png', fullPage: true });
  expect(edges.filter(e => e.label).map(e => ({ id: e.id, label: e.label }))).toEqual([
    { id: extra('803'), label: '已修改' },
  ]);
  await page.locator('.lineage-entry-list > summary').click();
  await page.locator('[data-lineage-relation]').filter({ hasText: 'Node 1' }).click();
  expect((await renderedEdges()).filter(e => e.label).map(e => e.id)).toEqual([extra('803')]);
  await expect(page.locator('[data-change-next]')).toBeEnabled();
  expect(requests.writes).toEqual([]);
});
