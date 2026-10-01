import { expect,test } from '@playwright/test';
const id=(n:number)=>'92000000-0000-4000-8000-'+String(n).padStart(12,'0');
test('article roles persist with evidence and independent status across article and graph views',async({page})=>{
 const paper=id(1),wid=id(2),lid=id(3);let version=1;
 const compounds=[1,2].map(n=>({id:id(10+n),paper_id:paper,workspace_id:wid,compound_label:String(n),display_name:'Synthetic compound '+n,description:null,sort_order:n,created_by_kind:'reviewer'}));
 const source={id:id(30),paper_id:paper,workspace_id:wid,kind:'text',source_sha256:'a'.repeat(64),page_number:2,bbox:null,quoted_text:'Synthetic author choice: start with compound 1 and prioritize compound 2 after combined assay and exposure analysis.',caption:'Synthetic example only',crop_asset_id:null,reviewer_note:null};
 const highlights:any[]=[];
 const workspace=()=>({id:wid,review_task_id:id(4),assigned_reviewer_id:id(5),state:'editing',version,task_status:'assigned',bibliography:{paper_id:paper,paper_key:'SYNTHETIC-HIGHLIGHTS',title:'Synthetic article compound highlights',journal:'UI test fixture',publication_year:2026,volume:'1',issue:'1',doi:null},source:{asset_id:id(6),source_root_key:'source_pdfs',source_key:'synthetic.pdf',sha256:'a'.repeat(64),page_count:2},sections:['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}))});
 const lineage={id:lid,paper_id:paper,workspace_id:wid,lineage_label:'Synthetic SAR series',lineage_type:'sar',description:null,sort_order:0,members:compounds.map((c,i)=>({id:id(40+i),paper_id:paper,workspace_id:wid,lineage_id:lid,compound_id:c.id,role:i?'terminal':'root',sort_order:i})),edges:[{id:id(50),paper_id:paper,workspace_id:wid,lineage_id:lid,parent_compound_id:compounds[0]!.id,child_compound_id:compounds[1]!.id,relation_type:'lead_optimization',modification_summary:'Synthetic comparison',review_status:'draft',sort_order:0}]};
 await page.route('**/api/v*/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;
  const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if(path==='/api/v1/auth/session')return reply({user:{username:'reviewer',display_name:'Synthetic reviewer',role:'reviewer',must_change_password:false},csrf_token:'test-csrf'});
  if(path.endsWith('/review-progress'))return reply({workspace_id:wid,workspace_version:version,tracking_started:false,items:[],sections:[]});
  if(path.endsWith('/compound-highlights')){
   if(req.method()==='POST'){
    const {expected_workspace_version,...data}=req.postDataJSON();expect(expected_workspace_version).toBe(version);expect(req.headers()['x-csrf-token']).toBe('test-csrf');
    const item={...data,id:id(60+highlights.length),workspace_id:wid,paper_id:paper,created_by_kind:'reviewer'};highlights.push(item);version++;return reply({highlight:item,workspace_version:version},201);
   }return reply({workspace_id:wid,workspace_version:version,items:highlights,total:highlights.length});
  }
  if(path.endsWith('/compounds'))return reply({workspace_id:wid,workspace_version:version,items:compounds,total:compounds.length});
  if(path.endsWith('/evidence'))return reply({workspace_id:wid,workspace_version:version,items:[source],total:1});
  if(path.endsWith('/lineages'))return reply({workspace_id:wid,workspace_version:version,items:[lineage],total:1});
  if(path.includes('/layouts/'))return reply({revision:0,mode:path.split('/').at(-1),positions:{},edge_controls:{}});
  if(path.endsWith('/structure'))return reply({structure:null,workspace_version:version});
  if(path.endsWith('/depiction'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 100"><path d="M30 60L70 30L110 60L150 30L190 60" fill="none" stroke="#234" stroke-width="3"/><text x="10" y="95" font-size="10">SYNTHETIC UI EXAMPLE</text></svg>'});
  if(path==='/api/v2/workspaces/'+wid)return reply(workspace());
  return reply({workspace_version:version,items:[],total:0});
 });
 await page.goto('/review/papers/'+paper+'?workspace='+wid);
 for(const [i,role,status] of [[0,'study_start','reviewer_confirmed'],[1,'paper_selected','draft']] as const){
  await page.locator('[data-add-highlight]').click();
  await page.locator('[data-highlight-compound]').selectOption(compounds[i]!.id);
  await page.locator('[data-highlight-role]').selectOption(role);
  await page.locator('[data-highlight-scope]').fill('Series A');
  await page.locator('[data-highlight-rationale]').fill(i?'Prioritized using activity and exposure (synthetic example).':'Starting lead chosen by the authors (synthetic example).');
  await page.locator('[data-highlight-evidence]').selectOption(source.id);
  await page.locator('select[data-highlight-status]').selectOption(status);
  await page.locator('[data-save-highlight]').click();
  await expect(page.locator('[data-highlight-form]')).toHaveCount(0);
 }
 await expect(page.locator('.highlight-card')).toHaveCount(2);expect(highlights.map(x=>x.review_status)).toEqual(['reviewer_confirmed','draft']);
 await page.locator('[data-language-switch]').selectOption('en');
 await expect(page.locator('[data-paper-highlights]')).toContainText('Paper-prioritized compound');
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:process.env.HIGHLIGHTS_SCREENSHOT||'test-results/paper-highlights-example.png',fullPage:true});
 await page.locator('[data-workspace-tab]').filter({hasText:/^Lineage$/}).click();
 const graph=page.locator('[data-lineage-graph]');await expect(graph).toHaveAttribute('data-node-count','2');
 await expect.poll(()=>graph.evaluate((el:any)=>(el._cyreg?.cy?.nodes().map((n:any)=>n.data('label'))??[]).join('|'))).toContain('Paper-prioritized compound ?');
 expect(highlights[1].review_status).toBe('draft');
});
