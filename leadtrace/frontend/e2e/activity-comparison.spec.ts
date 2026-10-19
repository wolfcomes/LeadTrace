import { test, expect, type Page } from '@playwright/test';
const id = (n:number) => '92000000-0000-4000-8000-'+String(n).padStart(12,'0');
async function fixture(page:Page, uniqueConditions=false, source=false) {
  const wid=id(2),paper=id(1);let version=1;
  const compounds=Array.from({length:40},(_,i)=>({id:id(100+i),paper_id:paper,workspace_id:wid,compound_label:'C'+(i+1),display_name:'Synthetic compound '+(i+1),description:null,sort_order:i,created_by_kind:'reviewer'}));
  const activities=compounds.slice(0,30).flatMap((c,i)=>Array.from({length:6},(_,j)=>({id:id(1000+i*10+j),paper_id:paper,workspace_id:wid,compound_id:c.id,evidence_id:null,assay_name:'Synthetic assay '+(j+1),metric:'IC50',operator:j===1?'>':'=',value:String(i+j+1),unit:'nM',context:j===0&&i>=24?'Mouse enzyme':'Human enzyme',review_hint:j===0?'Verify this measurement':null,sort_order:j})).filter(a=>a.assay_name!=='Synthetic assay 2'||i<20));
  if(uniqueConditions) {
    for(const a of activities)a.context='Condition for '+a.compound_id+' in '+a.assay_name;
    activities.push(...activities.filter(a=>a.assay_name==='Synthetic assay 1').map((a,i)=>({...a,id:id(9000+i),context:'Second condition for '+a.compound_id,operator:'<',value:'0.25'})));
  }
  const ws=()=>({id:wid,review_task_id:id(3),assigned_reviewer_id:id(4),state:'editing',version,task_status:'assigned',bibliography:{paper_id:paper,paper_key:'SYNTHETIC-COMPARISON',title:'Synthetic activity comparison',journal:'Fixtures',publication_year:2026,volume:'1',issue:'1',doi:null},source:{asset_id:id(5),source_root_key:'source_pdfs',source_key:'synthetic.pdf',sha256:'a'.repeat(64),page_count:1},sections:['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}))});
  let tables:any[]=source?[{id:id(80),paper_id:paper,workspace_id:wid,name:'Table 1',kind:'source',source_label:'Table 1',source_title:'Synthetic activity table',page_number:1,review_hint:null,review_status:'draft',created_by_kind:'ai',columns:[{id:'source-a',label:'Primary potency',assay:'Synthetic assay 1',metric:'IC50',unit:'nM',activity_ids:activities.filter(a=>a.assay_name==='Synthetic assay 1').map(a=>a.id)}],mode:'any',sort:'label'}]:[];
  const writes:{path:string;body:any}[]=[];
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(req.method()!=='GET')writes.push({path,body:req.postDataJSON()});
    if(path==='/api/v1/auth/session')return reply({user:{username:'reviewer',display_name:'Reviewer',role:'reviewer',must_change_password:false},csrf_token:'test-csrf'});
    if(path.includes('/activity-tables')){
      if(req.method()==='GET')return reply({workspace_id:wid,workspace_version:version,tables,other_activity_ids:activities.filter(a=>!tables.some(t=>t.columns.some((c:any)=>c.activity_ids.includes(a.id)))).map(a=>a.id)});
      const body=req.postDataJSON();if(body.expected_workspace_version!==version)return reply({error:{code:'WORKSPACE_VERSION_CONFLICT',message:'Conflict'}},409);
      version++;const tid=path.split('/').at(path.endsWith('/confirm')?-2:-1)!;
      if(req.method()==='DELETE'){tables=tables.filter(t=>t.id!==tid);return reply({deleted_table_id:tid,workspace_version:version});}
      const table=path.endsWith('/confirm')?{...tables.find(t=>t.id===tid),review_status:'reviewer_confirmed'}:{...body,id:tid,paper_id:paper,workspace_id:wid,created_by_kind:'reviewer',review_status:'draft'};
      tables=tables.filter(t=>t.id!==tid).concat(table);return reply({workspace_version:version,table});
    }
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


async function addColumn(page:Page, assay:string, title:string, condition?:string) {
 await page.locator('[data-add-column]').click();
 await page.locator('[data-column-measurement]').selectOption(JSON.stringify([assay,'IC50','nM']));
 await page.locator('[data-column-label]').fill(title);
 if(condition){
  await page.locator('[data-column-scope]').selectOption('selected');
  await page.locator('[data-column-record-search]').fill(condition);
  await page.locator('[data-column-select-filtered]').click();
 }
 await page.locator('[data-column-apply]').click();
}

test('build, save, reorder, edit an exact Activity and return on desktop and mobile',async({page})=>{
 const f=await fixture(page),errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`/review/papers/${f.paper}?workspace=${f.wid}&tab=activity-comparison`);
 await expect(page.locator('[data-comparison-row]')).toHaveCount(30);
 await page.locator('[data-new-table]').click();
 await addColumn(page,'Synthetic assay 1','Human assay 1','Human enzyme');
 await expect(page.locator('[data-comparison-row]')).toHaveCount(24);
 await addColumn(page,'Synthetic assay 1','Mouse assay 1','Mouse enzyme');
 await addColumn(page,'Synthetic assay 2','Assay 2');
 await expect(page.locator('[data-comparison-column]')).toHaveCount(3);
 await expect(page.locator('[data-comparison-row]')).toHaveCount(30);
 await page.locator('[data-comparison-row-mode]').selectOption('all');
 await expect(page.locator('[data-comparison-row]')).toHaveCount(0);
 await page.locator('[data-column-remove]').nth(1).click();
 await expect(page.locator('[data-comparison-row]')).toHaveCount(20);
 await page.locator('[data-comparison-row-mode]').selectOption('any');
 await expect(page.locator('[data-comparison-row]')).toHaveCount(24);
 await page.locator('[data-column-move-left]').nth(1).click();
 await expect(page.locator('[data-comparison-column]').first()).toContainText('Assay 2');
 await page.locator('[data-table-name]').fill('Primary comparison');
 await page.locator('[data-save-table]').click();
 await expect(page.getByRole('status')).toContainText('表格已保存到文章工作区');
 await page.reload();
 await expect(page.locator('[data-table-name]')).toHaveValue('Primary comparison');
 await expect(page.locator('[data-comparison-row]')).toHaveCount(24);
 await expect(page.locator('[data-comparison-column]').first()).toContainText('Assay 2');
 await page.locator('[data-comparison-search]').fill('compound 2');
 const target=f.activities.find(a=>a.compound_id===f.compounds[1]!.id&&a.assay_name==='Synthetic assay 2')!;
 expect(f.writes).toHaveLength(1);
 await page.locator(`[data-comparison-activity][data-activity-id="${target.id}"]`).click();
 const focused=page.locator(`[data-activity-row][data-activity-id="${target.id}"]`);
 await expect(focused).toHaveClass(/selected/);
 await focused.locator('[data-edit-activity]').click();await page.locator('[data-edit-activity-value]').fill('0.125');
 await expect(page.locator('[data-return-comparison]')).toBeDisabled();await page.locator('[data-save-activity-edit]').click();
 await expect(page.locator('[data-return-comparison]')).toBeEnabled();await page.locator('[data-return-comparison]').click();
 await expect(page.locator('[data-comparison-search]')).toHaveValue('compound 2');
 await expect(page.locator(`[data-comparison-activity][data-activity-id="${target.id}"]`)).toContainText('0.125');
 await expect(page.locator('[data-comparison-column]').first()).toContainText('Assay 2');
 expect(f.writes).toHaveLength(2);expect(f.writes[1]!.path).toBe('/api/v2/activities/'+target.id);
 await page.locator('[data-comparison-search]').fill('');await page.locator('[data-toggle-column-config]').click();
 await page.locator('[data-activity-comparison]').screenshot({path:'test-results/activity-table-builder-desktop.png'});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
 await page.locator('[data-activity-comparison]').screenshot({path:'test-results/activity-table-builder-mobile.png'});
 await page.locator('[data-add-column]').click();
 await page.locator('[data-column-measurement]').selectOption(JSON.stringify(['Synthetic assay 1','IC50','nM']));
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
 await page.locator('[data-column-editor]').screenshot({path:'test-results/activity-table-builder-column-mobile.png'});
 expect(errors).toEqual([]);
});

test('keeps repeated observations and per-Compound conditions with explicit record selection',async({page})=>{
 const f=await fixture(page,true);
 await page.goto(`/review/papers/${f.paper}?workspace=${f.wid}&tab=activity-comparison`);
 await page.locator('[data-new-table]').click();
 await addColumn(page,'Synthetic assay 1','All assay 1 observations');
 await expect(page.locator('[data-comparison-row]')).toHaveCount(30);
 await expect(page.locator('[data-comparison-activity]')).toHaveCount(60);
 await page.locator('[data-column-edit]').click();
 await page.locator('[data-column-scope]').selectOption('selected');
 await page.locator('[data-column-deselect-filtered]').click();
 await page.locator('[data-column-record-search]').fill('Second condition');
 await page.locator('[data-column-select-filtered]').click();
 await page.locator('[data-column-apply]').click();
 await expect(page.locator('[data-comparison-row]')).toHaveCount(30);
 await expect(page.locator('[data-comparison-activity]')).toHaveCount(30);
 const selected=page.locator('[data-comparison-activity]').first(),selectedId=await selected.getAttribute('data-activity-id');
 await selected.click();await expect(page.locator(`[data-activity-row][data-activity-id="${selectedId}"]`)).toHaveClass(/selected/);
 await page.locator('[data-return-comparison]').click();await expect(page.locator('[data-comparison-activity]')).toHaveCount(30);
 expect(f.writes).toHaveLength(0);
});


test('opens original source Table, confirms explicitly and derives Other after deletion',async({page})=>{
 const f=await fixture(page,false,true),errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`/review/papers/${f.paper}?workspace=${f.wid}&tab=activity-comparison`);
 await expect(page.locator('[data-table-name]')).toHaveValue('Table 1');
 await expect(page.locator('[data-source-title]')).toHaveValue('Synthetic activity table');
 await expect(page.locator('[data-comparison-row]')).toHaveCount(30);
 expect(f.writes).toHaveLength(0);
 await page.locator('[data-confirm-table]').click();await expect(page.locator('[data-table-review-status]')).toContainText('表格已确认');
 await page.reload();await expect(page.locator('[data-confirm-table]')).toHaveCount(0);
 await page.locator('[data-table-name]').fill('Reviewer title');await page.locator('[data-save-table]').click();
 await expect(page.locator('[data-confirm-table]')).toBeEnabled();
 await page.locator('[data-saved-table]').selectOption('other');
 await expect(page.locator('[data-comparison-activity]')).toHaveCount(f.activities.length-30);
 await expect(page.locator('[data-delete-table]')).toHaveCount(0);
 await page.locator('[data-saved-table]').selectOption(id(80));await page.locator('[data-delete-table]').click();await page.locator('[data-discard-table-changes]').click();
 await expect(page.locator('[data-saved-table]')).toHaveValue('other');await expect(page.locator('[data-comparison-activity]')).toHaveCount(f.activities.length);
 expect(f.writes).toHaveLength(3);expect(errors).toEqual([]);
});
