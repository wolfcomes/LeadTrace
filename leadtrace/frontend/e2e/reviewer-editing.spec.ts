import {expect, test, type Page} from '@playwright/test';
const id = (n:number) => '91000000-0000-4000-8000-' + String(n).padStart(12,'0');
async function fixture(page:Page) {
 let version=1, undone=false, submitted=false; const wid=id(2), paper=id(1), viewed=new Set<string>();
 const compounds=[0,1,2].map(i=>({id:id(100+i),paper_id:paper,workspace_id:wid,compound_label:'C'+(i+1),display_name:'Synthetic compound '+(i+1),description:null,sort_order:i,created_by_kind:'reviewer'}));
 const lineages=[0,1].map(i=>({id:id(200+i),paper_id:paper,workspace_id:wid,lineage_label:'Synthetic series '+(i+1),lineage_type:i?'synthesis':'sar',description:'Synthetic UI fixture',sort_order:i,members:[{id:id(300+i),paper_id:paper,workspace_id:wid,lineage_id:id(200+i),compound_id:compounds[i]!.id,role:'root',sort_order:0}],edges:[]}));
 for (const l of lineages) {
  l.members.push({...l.members[0]!,id:id(350+l.sort_order),compound_id:compounds[2]!.id,role:'terminal',sort_order:1});
  (l.edges as any[]).push({id:id(400+l.sort_order),paper_id:paper,workspace_id:wid,lineage_id:l.id,parent_compound_id:l.members[0]!.compound_id,child_compound_id:compounds[2]!.id,relation_type:'optimization',modification_summary:null,review_hint:null,review_status:'draft',sort_order:0});
 }
 const ws=()=>({id:wid,review_task_id:id(3),assigned_reviewer_id:id(4),state:submitted?'submitted':'editing',version,task_status:submitted?'submitted':'assigned',bibliography:{paper_id:paper,paper_key:'SYNTHETIC-EDITING',title:'Synthetic editing fixture',journal:'Fixtures',publication_year:2026,volume:'1',issue:'1',doi:null},source:{asset_id:id(5),source_root_key:'source_pdfs',source_key:'synthetic.pdf',sha256:'a'.repeat(64),page_count:1},sections:['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}))});
 const history=()=>({workspace_version:version,undo_action:undone?null:'compound.update',redo_action:undone?'compound.update':null});
 const progress=()=>({workspace_id:wid,workspace_version:version,tracking_started:viewed.size>0,items:lineages.map(l=>({kind:'lineage',entity_id:l.id,section_key:'lineages',label:l.lineage_label,signature:'a'.repeat(64),viewed:viewed.has(l.id)})),sections:[]});
 const writes:{path:string;body:any;headers:Record<string,string>}[]=[];
 await page.route('**/api/v*/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname,method=req.method();
  const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if(method!=='GET') writes.push({path,body:req.postDataJSON(),headers:req.headers()});
  if(path==='/api/v1/auth/session')return reply({user:{username:'reviewer',display_name:'Synthetic reviewer',role:'reviewer',must_change_password:false},csrf_token:'editing-csrf'});
  if(path.endsWith('/edit-history/undo')||path.endsWith('/edit-history/redo')){version++;undone=path.endsWith('/undo');return reply(history());}
  if(path.endsWith('/edit-history'))return reply(history());
  if(path.endsWith('/confirm')){const l=lineages.find(l=>path.includes(l.id))!;for(const e of l.edges as any[])e.review_status='reviewer_confirmed';version++;viewed.add(l.id);return reply({lineage:l,workspace_version:version});} if(path.endsWith('/review-progress'))return reply(progress());
  if(path.endsWith('/views')){const b=req.postDataJSON();b.viewed?viewed.add(b.entity_id):viewed.delete(b.entity_id);return reply(progress());}
  if(path.includes('/clipboard/')){const b=req.postDataJSON();version++;compounds.push({...compounds[0]!,id:id(199),compound_label:b.label,display_name:b.display_name,sort_order:3});return reply({entity_id:id(199),workspace_version:version},201);}
  if(path.endsWith('/submit-problem')){version++;submitted=true;return reply({workspace_version:version});}
  if(path.endsWith('/submission-validation'))return reply({workspace_id:wid,workspace_version:version,valid:false,blockers:[{code:'STRUCTURE_NOT_CONFIRMED',message:'Synthetic structure requires confirmation',entity_type:'compound',entity_id:compounds[0]!.id,section_key:'structures'}]});
  if(path.endsWith('/compounds'))return reply({workspace_id:wid,workspace_version:version,items:compounds,total:compounds.length});
  if(path.endsWith('/lineages'))return reply({workspace_id:wid,workspace_version:version,items:lineages,total:lineages.length});
  if(path.includes('/layouts/'))return reply({revision:0,mode:path.split('/').at(-1),positions:{},edge_controls:{}});
  if(path.endsWith('/structure'))return reply({workspace_version:version,structure:null});
  if(['/activities','/source-images'].some(s=>path.endsWith(s)))return reply({compound_id:path.split('/').at(-2),workspace_version:version,items:[],total:0});
  if(path.endsWith('/evidence-links'))return reply({edge_id:path.split('/').at(-2),workspace_version:version,items:[],total:0});
  if(['/evidence','/compound-highlights'].some(s=>path.endsWith(s)))return reply({workspace_id:wid,workspace_version:version,items:[],total:0});
  if(path==='/api/v2/workspaces/'+wid)return reply(ws());
  return reply({},404);
 });
 return {paper,wid,compounds,lineages,writes};
}

test('undo and redo respect unsaved edits and clipboard starts with blank identity',async({page})=>{
 const f=await fixture(page);await page.goto('/review/papers/'+f.paper+'?workspace='+f.wid+'&tab=compounds');
 await expect(page.locator('[data-undo]')).toBeEnabled();await page.locator('[data-edit-compound]').first().click();await page.locator('[data-edit-compound-label]').fill('Unsaved');await expect(page.locator('[data-undo]')).toBeDisabled();
 await page.locator('.compound-edit-form').getByRole('button',{name:'取消',exact:true}).click();await page.locator('[data-undo]').click();await expect(page.locator('[data-redo]')).toBeEnabled();await page.locator('[data-redo]').click();await expect(page.locator('[data-undo]')).toBeEnabled();
 expect(f.writes.filter(x=>x.path.includes('/edit-history/')).map(x=>x.body.expected_workspace_version)).toEqual([1,2]);
 await page.locator('[data-copy-record]').click();await page.locator('[data-paste-record]').click();await expect(page.locator('[data-paste-label]')).toHaveValue('');await expect(page.locator('[data-paste-name]')).toHaveValue('');await expect(page.locator('[data-undo]')).toBeDisabled();
 await page.locator('[data-paste-label]').fill('C1');await expect(page.locator('[data-confirm-paste]')).toBeDisabled();await page.locator('[data-paste-label]').fill('C4');await page.locator('[data-paste-name]').fill('Synthetic compound 1');await expect(page.locator('[data-clipboard-name-warning]')).toBeVisible();await expect(page.locator('[data-confirm-paste]')).toBeEnabled();
 await expect.poll(async()=> (await page.locator('[data-paste-label]').boundingBox())?.width ?? 0).toBeGreaterThan(180);
 await page.setViewportSize({width:390,height:844});await expect.poll(async()=> (await page.locator('[data-paste-label]').boundingBox())?.width ?? 0).toBeGreaterThan(180);await expect(page.locator('[data-confirm-paste]')).toBeVisible();await page.screenshot({path:'test-results/reviewer-editing-clipboard-mobile.png',fullPage:true});await page.setViewportSize({width:1280,height:720});
 await page.screenshot({path:'test-results/reviewer-editing-clipboard.png',fullPage:true});await page.locator('[data-confirm-paste]').click();await expect(page.locator('[data-compound-row]')).toHaveCount(4);expect(f.writes.find(x=>x.path.endsWith('/clipboard/compound'))?.body).toEqual({source_id:f.compounds[0]!.id,expected_workspace_version:3,label:'C4',display_name:'Synthetic compound 1'});
});

test('Lineage search focuses a node and batch confirmation avoids Edge navigation',async({page})=>{
 const f=await fixture(page);await page.goto('/review/papers/'+f.paper+'?workspace='+f.wid+'&tab=lineages');
 await page.locator('[data-lineage-compound-search]').fill('synthetic compound 2');await expect(page.locator('[data-lineage-search-result]')).toHaveCount(1);await page.locator('[data-lineage-search-result]').click();
 await expect(page.locator('[data-lineage-group=synthesis]')).toHaveAttribute('aria-pressed','true');await expect(page.locator('[data-graph-locate]')).toHaveValue(f.compounds[1]!.id);
 await expect.poll(()=>page.locator('[data-lineage-graph]').evaluate((el:any,cid)=>el._cyreg?.cy?.getElementById(cid).hasClass('focused')??false,f.compounds[1]!.id)).toBe(true);expect(f.writes.filter(x=>x.path.endsWith('/views'))).toHaveLength(0);
 await page.locator('[data-confirm-lineage]').click();await expect(page.locator('[data-confirm-lineage]')).toBeDisabled();expect(f.writes.find(x=>x.path.endsWith('/confirm'))).toMatchObject({path:'/api/v2/lineages/'+f.lineages[1]!.id+'/confirm',body:{expected_workspace_version:1}});expect((f.lineages[1]!.edges as any[])[0].review_status).toBe('reviewer_confirmed');
 await expect(page.locator('[data-lineage-view=graph]')).toBeVisible();await page.screenshot({path:'test-results/reviewer-editing-lineage.png',fullPage:true});
});

test('problem submission requires explanation without normal confirmation',async({page})=>{
 const f=await fixture(page);await page.goto('/review/papers/'+f.paper+'?workspace='+f.wid+'&tab=submit');await expect(page.locator('[data-submit-paper]')).toBeDisabled();await expect(page.locator('[data-submit-problem]')).toBeDisabled();
 await page.locator('[data-problem-reason]').fill('Synthetic article has contradictory identities.');await expect(page.locator('[data-reviewer-confirmation]')).not.toBeChecked();await expect(page.locator('[data-submit-problem]')).toBeEnabled();
 await page.screenshot({path:'test-results/reviewer-editing-problem.png',fullPage:true});await page.locator('[data-submit-problem]').click();await expect(page.getByText('文章问题已提交',{exact:true})).toBeVisible();
 const sent=f.writes.find(x=>x.path.endsWith('/submit-problem'));expect(sent?.body).toEqual({expected_workspace_version:1,reason:'Synthetic article has contradictory identities.'});expect(sent?.headers['idempotency-key']).toMatch(/^problem-/);expect(f.writes.some(x=>x.path.endsWith('/submit'))).toBe(false);
});
