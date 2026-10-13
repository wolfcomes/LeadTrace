import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { expect, test, type Page } from '@playwright/test';
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

test('complete compound records align before/after and original evidence is directly visible',async({page})=>{
  await page.setViewportSize({width:1536,height:1100});
  const requests=await setup(page);
  await page.locator('[data-record-tab="compounds"]').click();
  await page.locator(`[data-record-entry="${ids.compoundB}"]`).click();
  const before=page.locator('[data-record-side="before"]'),after=page.locator('[data-record-side="after"]');
  await expect(before).toContainText('Cell potency');await expect(after).toContainText('Human cells');
  await expect(before).toContainText('125');await expect(after).toContainText('12.5');
  const crop=after.locator('[data-evidence-thumbnail]').first();await after.locator('[data-frozen-evidence]').first().scrollIntoViewIfNeeded();await expect(crop).toBeVisible();
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
  await page.locator('[data-full-submission] [data-frozen-evidence]').first().scrollIntoViewIfNeeded();
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
  await page.locator(`[data-lineage-relation][data-edge-id="${ids.edge}"]`).click();
  await expect(before).toHaveAttribute('data-selected-id',ids.edge);await expect(after).toHaveAttribute('data-selected-id',ids.edge);
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
  await page.locator('[data-graph-expand]').click();
  await expect(page.locator('[data-lineage-comparison]')).toBeVisible();
  await page.screenshot({path:'test-results/approval-records-lineage.png'});
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
  await side.locator('[data-frozen-evidence]').first().scrollIntoViewIfNeeded();
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
