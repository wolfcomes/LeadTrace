import { expect, test } from '@playwright/test';
const id=(n:number)=>`90000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
test('large graph supports dragging, curves, persistence and selecting existing compounds',async({page})=>{
 page.on('pageerror', e=>console.log('PAGE ERROR',e.message)); page.on('console',m=>{if(m.type()==='error')console.log('CONSOLE',m.text())});
 let version=1; const paper=id(1),wid=id(2),lid=id(3);
 const compounds=Array.from({length:122},(_,i)=>({id:id(100+i),paper_id:paper,workspace_id:wid,compound_label:String(i+1),display_name:null,description:null,sort_order:i,created_by_kind:'ai'}));
 const members=compounds.slice(0,120).map((c,i)=>({id:id(200+i),paper_id:paper,workspace_id:wid,lineage_id:lid,compound_id:c.id,role:i===0?'root':i===119?'terminal':'intermediate',sort_order:i}));
 const edges=compounds.slice(1,120).map((c,i)=>({id:id(300+i),paper_id:paper,workspace_id:wid,lineage_id:lid,parent_compound_id:compounds[i]!.id,child_compound_id:c.id,relation_type:'lead_optimization',modification_summary:'Synthetic substituent comparison',review_status:'draft',sort_order:i}));
 for(let i=0;i<61;i++)edges.push({...edges[i]!,id:id(500+i),child_compound_id:compounds[i+2]!.id,sort_order:119+i});
 const lineage=()=>({id:lid,paper_id:paper,workspace_id:wid,lineage_label:'Synthetic 120-node series',lineage_type:'sar',description:'UI test data only',sort_order:0,members,edges});
 const workspace=()=>({id:wid,review_task_id:id(4),assigned_reviewer_id:id(5),state:'editing',version,task_status:'assigned',bibliography:{paper_id:paper,paper_key:'SYNTHETIC-UI-TEST',title:'Synthetic reviewer workbench example',journal:'UI test fixture',publication_year:2026,volume:'1',issue:'1',doi:null},source:{asset_id:id(6),source_root_key:'source_pdfs',source_key:'synthetic.pdf',sha256:'a'.repeat(64),page_count:1},sections:['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}))});
 const layouts:Record<string,any>={points:{revision:0,mode:'points',positions:Object.fromEntries(compounds.slice(0,120).map((c,i)=>[c.id,{x:(i%12)*160,y:Math.floor(i/12)*110}])),edge_controls:{}},structures:{revision:0,mode:'structures',positions:{},edge_controls:{}}};
 const writes:{path:string;body:any}[]=[];
 await page.route('**/api/v*/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname,method=request.method();
  const reply=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if(method!=='GET')writes.push({path,body:request.postDataJSON()});
  if(path==='/api/v1/auth/session')return reply({user:{username:'reviewer',display_name:'Synthetic reviewer',role:'reviewer',must_change_password:false},csrf_token:'test-csrf'});
  if(path.endsWith('/review-progress'))return reply({workspace_id:wid,workspace_version:version,tracking_started:false,items:[],sections:workspace().sections.map(x=>({...x,total:0,viewed:0,complete:false}))});
  if(path.includes('/layouts/')){const mode=path.split('/').at(-1)!;if(method==='PUT'){const body=request.postDataJSON();if(body.expected_revision!==layouts[mode].revision)return reply({},409);layouts[mode]={...layouts[mode],positions:body.positions,edge_controls:body.edge_controls,revision:layouts[mode].revision+1};}return reply(layouts[mode]);}
  if(path.endsWith('/members')&&method==='POST'){const body=request.postDataJSON(),member={...members[0]!,id:id(999),compound_id:body.compound_id,role:body.role,sort_order:members.length};members.push(member);version++;return reply({member,workspace_version:version},201);}
  if(path.endsWith('/compounds'))return reply({workspace_id:wid,workspace_version:version,items:compounds,total:compounds.length});
  if(path.endsWith('/lineages'))return reply({workspace_id:wid,workspace_version:version,items:[lineage()],total:1});
  if(path.endsWith('/structure'))return reply({workspace_version:version,structure:null});
  if(['/evidence','/evidence-links','/activities','/structure-source-images'].some(x=>path.endsWith(x)))return reply({workspace_id:wid,compound_id:path.split('/').at(-2),edge_id:path.split('/').at(-2),workspace_version:version,items:[],total:0});
  if(path===`/api/v2/workspaces/${wid}`)return reply(workspace());
  return reply({},404);
 });
 await page.goto(`/review/papers/${paper}?workspace=${wid}&tab=lineages`);
 const canvas=page.locator('[data-lineage-graph]');
 await expect(canvas).toHaveAttribute('data-node-count','120');
 await expect(page.locator('[data-lineage-view-tab]')).toHaveCount(3);
 async function point(nodeId:string){await canvas.scrollIntoViewIfNeeded();await expect.poll(()=>canvas.evaluate((el:any,id)=>!!el._cyreg?.cy?.getElementById(id).length,nodeId)).toBe(true);const pos=await canvas.evaluate((el:any,id)=>el._cyreg.cy.getElementById(id).renderedPosition(),nodeId);const box=(await canvas.boundingBox())!;return{x:box.x+pos.x,y:box.y+pos.y};}
 async function drag(nodeId:string,dx:number,dy:number){const p=await point(nodeId);await page.mouse.move(p.x,p.y);await page.mouse.down();await page.mouse.move(p.x+dx,p.y+dy,{steps:12});await page.mouse.up();}
 await drag(compounds[0]!.id,50,30);
 await expect(page.locator('[data-graph-save-layout]')).toBeEnabled();await page.locator('[data-graph-save-layout]').click();
 await expect.poll(()=>layouts.points.revision).toBe(1);const savedPoint={...layouts.points.positions[compounds[0]!.id]};expect(savedPoint).not.toEqual({x:0,y:0});
 await page.locator('[data-graph-bend]').click();await drag('bend-'+edges[0]!.id,10,55);await page.locator('[data-graph-save-layout]').click();await expect.poll(()=>layouts.points.revision).toBe(2);expect(Math.abs(layouts.points.edge_controls[edges[0]!.id].distance)).toBeGreaterThan(5);
 await page.reload();await expect(canvas).toHaveAttribute('data-node-count','120');await expect.poll(()=>canvas.evaluate((el:any,id)=>el._cyreg?.cy?.getElementById(id).position().x,compounds[0]!.id)).toBeCloseTo(savedPoint.x,1);
 await page.locator('[data-graph-add-node]').click();expect(writes.filter(x=>x.path.endsWith('/members'))).toHaveLength(0);
 const picker=page.locator('[data-graph-compound-picker]');
 const assertPickerLayout=async()=>{
   const heading=(await picker.locator('h4').boundingBox())!,description=(await picker.locator('p').first().boundingBox())!;
   const fields=await picker.locator('.form-field').all();
   expect(description.y).toBeGreaterThanOrEqual(heading.y+heading.height);
   let bottom=description.y+description.height;
   for(const field of fields){const box=(await field.boundingBox())!;expect(box.y).toBeGreaterThanOrEqual(bottom);expect(box.width).toBeGreaterThan(250);bottom=box.y+box.height;}
   expect(await picker.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
 };
 await assertPickerLayout();
 await page.locator('[data-cancel-graph-node]').click();
 await page.locator('[data-language-switch]').selectOption('en');
 await page.setViewportSize({width:390,height:844});
 await page.locator('[data-graph-add-node]').click();await assertPickerLayout();
 await expect(page.locator('[data-confirm-graph-node]')).toBeVisible();
 await page.locator('[data-cancel-graph-node]').click();
 await page.locator('[data-language-switch]').selectOption('zh-CN');
 await page.setViewportSize({width:1280,height:900});
 await page.locator('[data-graph-add-node]').click();

 await page.locator('[data-graph-compound-select]').selectOption(compounds[120]!.id);await page.locator('[data-confirm-graph-node]').click();await expect(canvas).toHaveAttribute('data-node-count','121');expect(writes.filter(x=>x.path.endsWith('/members'))[0]?.body).toMatchObject({compound_id:compounds[120]!.id,expected_workspace_version:1,role:'unspecified'});
 await page.locator('[data-graph-add-edge]').click();for(const c of [compounds[18]!,compounds[19]!]){const p=await point(c.id);await page.mouse.click(p.x,p.y);}
 await expect(page.locator('[data-lineage-view-tab="edges"]')).toHaveAttribute('aria-selected','true');await expect(page.locator('.edge-create-form select').nth(0)).toHaveValue(compounds[18]!.id);await expect(page.locator('.edge-create-form select').nth(1)).toHaveValue(compounds[19]!.id);expect(writes.filter(x=>x.path.endsWith('/edges'))).toHaveLength(0);
 await page.locator('[data-lineage-view-tab="graph"]').click();await page.locator('[data-graph-mode="structures"]').click();await expect(canvas).toHaveAttribute('data-display-mode','structures');await page.getByRole('button',{name:'重排为网格',exact:true}).click();await page.locator('[data-graph-save-layout]').click();await expect.poll(()=>layouts.structures.revision).toBe(1);expect(layouts.points.revision).toBe(2);
 await page.locator('[data-graph-mode="points"]').click();await page.screenshot({path:process.env.WORKBENCH_SCREENSHOT||'test-results/reviewer-workbench.png',fullPage:true});await page.setViewportSize({width:800,height:900});await expect(page.locator('[data-lineage-view-tab="edges"]')).toBeVisible();
});
