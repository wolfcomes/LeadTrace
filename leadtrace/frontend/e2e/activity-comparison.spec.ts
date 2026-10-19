import { test, expect, type Page } from '@playwright/test';
const id = (n:number) => '92000000-0000-4000-8000-'+String(n).padStart(12,'0');
async function fixture(page:Page) {
  const wid=id(2),paper=id(1);let version=1;
  const compounds=Array.from({length:40},(_,i)=>({id:id(100+i),paper_id:paper,workspace_id:wid,compound_label:'C'+(i+1),display_name:'Synthetic compound '+(i+1),description:null,sort_order:i,created_by_kind:'reviewer'}));
  const activities=compounds.flatMap((c,i)=>Array.from({length:6},(_,j)=>({id:id(1000+i*10+j),paper_id:paper,workspace_id:wid,compound_id:c.id,evidence_id:null,assay_name:'Synthetic assay '+(j+1),metric:'IC50',operator:j===1?'>':'=',value:String(i+j+1),unit:'nM',context:j===2?'Mouse enzyme':'Human enzyme',review_hint:j===0?'Verify this measurement':null,sort_order:j})));
  const ws=()=>({id:wid,review_task_id:id(3),assigned_reviewer_id:id(4),state:'editing',version,task_status:'assigned',bibliography:{paper_id:paper,paper_key:'SYNTHETIC-COMPARISON',title:'Synthetic activity comparison',journal:'Fixtures',publication_year:2026,volume:'1',issue:'1',doi:null},source:{asset_id:id(5),source_root_key:'source_pdfs',source_key:'synthetic.pdf',sha256:'a'.repeat(64),page_count:1},sections:['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}))});
  const writes:{path:string;body:any}[]=[];
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(req.method()!=='GET')writes.push({path,body:req.postDataJSON()});
    if(path==='/api/v1/auth/session')return reply({user:{username:'reviewer',display_name:'Reviewer',role:'reviewer',must_change_password:false},csrf_token:'test-csrf'});
    if(path.endsWith('/activity-comparison'))return reply({workspace_id:wid,workspace_version:version,compounds,activities});
    if(path.startsWith('/api/v2/activities/')&&req.method()==='PATCH'){
      const a=activities.find(a=>path.endsWith(a.id))!;a.value=req.postDataJSON().value;version++;return reply({activity:a,workspace_version:version});
    }
    if(path.endsWith('/edit-history'))return reply({workspace_version:version,undo_action:null,redo_action:null});
    if(path.endsWith('/review-progress'))return reply({workspace_id:wid,workspace_version:version,tracking_started:false,items:[],sections:[]});
    if(path.endsWith('/compounds'))return reply({workspace_id:wid,workspace_version:version,items:compounds,total:compounds.length});
    if(path.endsWith('/structure'))return reply({workspace_version:version,structure:null});
    if(path.endsWith('/activities')){const cid=path.split('/').at(-2),items=activities.filter(a=>a.compound_id===cid);return reply({compound_id:cid,workspace_version:version,items,total:items.length});}
    if(path.endsWith('/source-images'))return reply({compound_id:path.split('/').at(-2),workspace_version:version,items:[],total:0});
    if(path.endsWith('/evidence')||path.endsWith('/compound-highlights'))return reply({workspace_id:wid,workspace_version:version,items:[],total:0});
    if(path==='/api/v2/workspaces/'+wid)return reply(ws());
    return reply({},404);
  });
  return {wid,paper,compounds,activities,writes};
}

test('compare, edit the selected Activity, and return to current saved data on desktop and mobile',async({page})=>{
  const f=await fixture(page);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`/review/papers/${f.paper}?workspace=${f.wid}&tab=activity-comparison`);
  await expect(page.locator('[data-comparison-row]')).toHaveCount(40);
  await expect(page.locator('[data-comparison-column]')).toHaveCount(6);
  await page.locator('[data-comparison-search]').fill('compound 2');
  await page.locator('[data-comparison-sort]').selectOption('label');
  await expect(page.locator('[data-comparison-row]')).toHaveCount(11);
  await page.locator('[data-comparison-scroll]').evaluate(el=>{el.scrollLeft=120;el.scrollTop=60;});
  const target=f.activities[11]!;
  expect(f.writes).toHaveLength(0);
  await page.locator(`[data-comparison-activity][data-activity-id="${target.id}"]`).click();
  const focused=page.locator(`[data-activity-row][data-activity-id="${target.id}"]`);
  await expect(focused).toHaveClass(/selected/);
  await expect(focused).toBeFocused();
  await focused.locator('[data-edit-activity]').click();
  await page.locator('[data-edit-activity-value]').fill('0.125');
  await expect(page.locator('[data-return-comparison]')).toBeDisabled();
  await page.locator('[data-save-activity-edit]').click();
  await expect(page.locator('[data-return-comparison]')).toBeEnabled();
  await page.locator('[data-return-comparison]').click();
  await expect(page.locator('[data-comparison-search]')).toHaveValue('compound 2');
  await expect(page.locator('[data-comparison-sort]')).toHaveValue('label');
  await expect(page.locator(`[data-comparison-activity][data-activity-id="${target.id}"]`)).toContainText('0.125');
  expect(f.writes).toHaveLength(1);
  expect(f.writes[0]!.path).toBe('/api/v2/activities/'+target.id);
  await page.locator('[data-comparison-scroll]').evaluate(el=>{el.scrollLeft=0;el.scrollTop=0;});
  await page.locator('[data-activity-comparison]').screenshot({path:'test-results/activity-comparison-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await page.locator('[data-activity-comparison]').scrollIntoViewIfNeeded();
  await expect(page.locator('[data-comparison-scroll]')).toBeVisible();
  const overflow=await page.evaluate(()=>Array.from(document.querySelectorAll('body *')).filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.right>window.innerWidth+2&&getComputedStyle(el).position!=='absolute';}).slice(0,15).map(el=>({tag:el.tagName,cls:el.className,width:el.getBoundingClientRect().width,right:el.getBoundingClientRect().right})));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2),JSON.stringify(overflow)).toBe(true);
  await page.locator('[data-activity-comparison]').screenshot({path:'test-results/activity-comparison-mobile.png'});
  await page.locator('[data-comparison-scroll]').evaluate(el=>el.scrollLeft=300);
  expect(await page.locator('[data-comparison-scroll]').evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});
