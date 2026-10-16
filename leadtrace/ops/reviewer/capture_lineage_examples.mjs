/** Capture real reviewer graphs with fictional data. Local frontend only; no live API/PDF. */
import {chromium} from '../../frontend/node_modules/playwright/index.mjs';
import {mkdirSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const origin=process.env.GUIDE_UI_ORIGIN||'http://127.0.0.1:5186';
assert.equal(new URL(origin).hostname,'127.0.0.1');
const out=fileURLToPath(new URL('../../frontend/public/reviewer-guide/images/',import.meta.url));
mkdirSync(out,{recursive:true});
const id=n=>`93000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const paper=id(1),wid=id(2),lid=id(3),sha='c'.repeat(64);
// Every relation below is an explicitly assumed fictional design/comparison, never inferred from numbering.
const examples=[
 {key:'parallel',title:['案例 1 · 同一基准的一批侧链优化','Case 1 · One baseline, one side-chain series'],desc:['虚构教学：以 1 为共同基准比较 2、3、4；同一主题，放在一张图。','FICTIONAL: compare 2, 3 and 4 against baseline 1; keep the shared theme together.'],nodes:[1,2,3,4],pairs:[[1,2],[1,3],[1,4]],positions:[[100,200],[480,50],[480,200],[480,350]]},
 {key:'hub-before',title:['案例 2A · 首轮优化，选出枢纽分子 3','Case 2A · First series selects hub compound 3'],desc:['虚构教学：1→2/3/4；作者选 3 开展下一批探索。3 在本图是 terminal。','FICTIONAL: 1→2/3/4; the authors select 3 for another series. 3 is terminal here.'],nodes:[1,2,3,4],pairs:[[1,2],[1,3],[1,4]],positions:[[100,200],[480,50],[480,200],[480,350]],hub:3},
 {key:'hub-after',title:['案例 2B · 从同一个 3 开展新一批优化','Case 2B · A new series from the same compound 3'],desc:['虚构教学：3→5/6/7；3 在本图是 root。作者优选 6；枢纽与优选分别判断。','FICTIONAL: 3→5/6/7; 3 is root here. The authors prioritize 6; hub and priority are distinct.'],nodes:[3,5,6,7],pairs:[[3,5],[3,6],[3,7]],positions:[[100,200],[480,50],[480,200],[480,350]],hub:3,selected:6},
 {key:'branch-a',title:['案例 3A · 共同起点 10，侧链优化分支','Case 3A · Side-chain branch from shared start 10'],desc:['虚构教学：以 10 为基准研究侧链变化；该组有独立主题与关系依据。','FICTIONAL: side-chain changes around 10 form an independently supported group.'],nodes:[10,11,12],pairs:[[10,11],[10,12]],positions:[[100,180],[480,70],[480,290]]},
 {key:'branch-b',title:['案例 3B · 共同起点 10，环系优化分支','Case 3B · Ring-system branch from shared start 10'],desc:['虚构教学：复用同一个 10，研究环系替换；与侧链组各自形成完整探索。','FICTIONAL: reuse 10 for ring-system changes, independently explored from the side-chain group.'],nodes:[10,21,22],pairs:[[10,21],[10,22]],positions:[[100,180],[480,70],[480,290]]},
 {key:'short-chain',title:['案例 4 · 连续短链，保留在一张图','Case 4 · Keep a short progression together'],desc:['虚构教学：30→31→32；围绕同一侧链问题，仅有两步设计，不必每一步拆图。','FICTIONAL: 30→31→32 addresses one side-chain question in two steps; keep it together.'],nodes:[30,31,32],pairs:[[30,31],[31,32]],positions:[[80,180],[340,180],[600,180]]},
 {key:'convergence',title:['案例 5 · 分支汇合，保留两条有依据的关系','Case 5 · Keep supported convergence visible'],desc:['虚构教学：40→41/42；作者分别以 41 和 42 比较 43。两条入边都有独立依据。','FICTIONAL: 40→41/42; the authors compare 43 against both 41 and 42, each with separate support.'],nodes:[40,41,42,43],pairs:[[40,41],[40,42],[41,43],[42,43]],positions:[[80,200],[340,60],[340,340],[600,200]]},
];
const browser=await chromium.launch({headless:true}),shots=[];
try{for(const lang of ['zh','en'])for(const example of examples){
 const tr=(zh,en)=>lang==='zh'?zh:en,ix=lang==='zh'?0:1;
 const context=await browser.newContext({viewport:{width:1500,height:1800},deviceScaleFactor:2});
 const page=await context.newPage(),errors=[],unknown=[];
 page.on('pageerror',error=>errors.push(error.message));
 // Prevent accidental external requests as well as live application access.
 await context.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(u.origin!==new URL(origin).origin){unknown.push(u.origin);return route.abort();}
  if(!u.pathname.startsWith('/api/'))return route.continue();
  const path=u.pathname,reply=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
  const list=items=>({workspace_id:wid,workspace_version:1,items,total:items.length});
  if(path==='/api/preview/environment')return reply({environment:'preview',instance_id:'fictional-lineage-guide'});
  if(path==='/api/v1/auth/session')return reply({user:{username:'fictional-reviewer',display_name:tr('虚构教学 Reviewer','Fictional teaching Reviewer'),role:'reviewer',must_change_password:false},csrf_token:'fictional-token'});
  if(path===`/api/v2/workspaces/${wid}`)return reply(ws);
  if(path.endsWith('/compounds'))return reply(list(compounds));
  if(path.endsWith('/lineages'))return reply(list([lineage]));
  if(path.endsWith('/compound-highlights'))return reply(list(highlights));
  if(path.endsWith('/evidence'))return reply(list(evidence));
  if(path.endsWith('/review-progress')||path.endsWith('/views'))return reply({workspace_id:wid,workspace_version:1,tracking_started:false,items:[],sections:[]});
  if(path.includes('/layouts/'))return reply({revision:1,mode:'points',positions:Object.fromEntries(example.nodes.map((n,i)=>[id(100+n),{x:example.positions[i][0],y:example.positions[i][1]}])),edge_controls:{}});
  if(path.endsWith('/structure'))return reply({workspace_version:1,structure:null});
  if(path.endsWith('/evidence-links'))return reply({workspace_version:1,edge_id:path.split('/').at(-2),items:[],total:0});
  unknown.push(path);return route.fulfill({status:404,body:'Unmocked teaching request'});
 });
 const compounds=example.nodes.map((n,i)=>({id:id(100+n),paper_id:paper,workspace_id:wid,compound_label:String(n),display_name:tr('虚构分子','Fictional compound'),description:tr('仅用于教学','Training only'),sort_order:i,created_by_kind:'reviewer'}));
 const members=example.nodes.map((n,i)=>({id:id(200+n),paper_id:paper,workspace_id:wid,lineage_id:lid,compound_id:id(100+n),role:!example.pairs.some(p=>p[1]===n)?'root':example.pairs.some(p=>p[0]===n)?'intermediate':'terminal',sort_order:i}));
 const edges=example.pairs.map(([a,b],i)=>({id:id(300+i),paper_id:paper,workspace_id:wid,lineage_id:lid,parent_compound_id:id(100+a),child_compound_id:id(100+b),relation_type:'sar_comparison',modification_summary:tr(`虚构的设计／比较关系 ${a}→${b}`,`Fictional design/comparison ${a}→${b}`),review_status:'reviewer_confirmed',sort_order:i}));
 const lineage={id:lid,paper_id:paper,workspace_id:wid,lineage_label:example.title[ix],lineage_type:'sar',description:example.desc[ix],sort_order:0,members,edges};
 const evidence=[{id:id(400),paper_id:paper,workspace_id:wid,kind:'text',source_sha256:sha,page_number:1,bbox:null,quoted_text:tr('虚构教学依据：假设作者明确陈述图中的设计／比较关系及标注理由。','FICTIONAL teaching evidence: assume explicit author support for the illustrated relationships and annotations.'),caption:tr('虚构依据，不对应论文','Fictional support, not a paper'),crop_asset_id:null,reviewer_note:null}];
 const highlights=[['optimization_start',example.hub],['paper_selected',example.selected]].filter(([,n])=>n).map(([role,n],i)=>({id:id(500+i),paper_id:paper,workspace_id:wid,compound_id:id(100+n),evidence_id:id(400),role,scope:tr('虚构系列','Fictional series'),rationale:tr('教学假设：作者有明确选择理由。','Teaching assumption: explicit author rationale.'),review_hint:null,review_status:'reviewer_confirmed',created_by_kind:'reviewer'}));
 const ws={id:wid,review_task_id:id(4),assigned_reviewer_id:id(5),state:'editing',version:1,task_status:'assigned',bibliography:{paper_id:paper,paper_key:'FICTIONAL-TRAINING',title:tr('虚构 Lineage 教学案例','Fictional Lineage teaching cases'),journal:'Training only',publication_year:2026,volume:'1',issue:'1',doi:null},source:{asset_id:id(6),source_root_key:'source_pdfs',source_key:'fictional-only.pdf',sha256:sha,page_count:1},sections:['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}))};
 await page.goto(`${origin}/review/papers/${paper}?workspace=${wid}&tab=lineages`);
 await page.locator('[data-language-switch]').selectOption(lang==='zh'?'zh-CN':'en');
 const graph=page.locator('[data-lineage-graph]');await graph.waitFor();
 await page.waitForFunction(({nodes,edges})=>{const cy=document.querySelector('[data-lineage-graph]')?._cyreg?.cy;return cy?.nodes().length===nodes&&cy?.edges().length===edges;},{nodes:members.length,edges:edges.length});
 await page.addStyleTag({content:'.topbar,.paper-workspace-tabs,.lineage-view-tabs,.language-toolbar,.preview-environment{position:static!important}'});
 await page.evaluate(async()=>{await document.fonts.load('600 14px "Noto Sans SC Variable"','枢纽分子论文优选');await document.fonts.ready;});
 // Use the app’s bundled font for canvas text on fontless capture hosts. No graph data/style geometry changes.
 await graph.evaluate(el=>{el._cyreg.cy.nodes().style('font-family','Noto Sans SC Variable');});
 await page.locator('.lineage-detail-panel').scrollIntoViewIfNeeded();
 await page.locator('[data-graph-readable]').click();
 await graph.evaluate(el=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const actual=await graph.evaluate(el=>({labels:el._cyreg.cy.nodes().map(n=>n.data('label')),pairs:el._cyreg.cy.edges().map(e=>[e.source().data('label').split('\n')[0],e.target().data('label').split('\n')[0]])}));
 assert.deepEqual(actual.pairs,example.pairs.map(p=>p.map(String)));
 if(example.hub)assert.ok(actual.labels.some(x=>x.includes(tr('枢纽分子','Hub compound'))));
 assert.deepEqual(errors,[]);assert.deepEqual(unknown,[]);assert.equal(await page.locator('[role=alert]').count(),0);
 const name=`lineage-example-${example.key}.${lang}.png`;
 await page.locator('.lineage-detail-panel').screenshot({path:out+name,animations:'disabled',style:'.lineage-view-tabs{position:static!important}'});
 shots.push({file:name,case:example.key,language:lang,node_count:members.length,edge_count:edges.length});
 await context.close();
}}finally{await browser.close();}
writeFileSync(out+'lineage-examples-manifest.json',JSON.stringify({kind:'real reviewer UI with fictional intercepted data',live_database_access:false,source_pdf_access:false,device_scale_factor:2,shots},null,2)+'\n');
console.log(`Captured and checked ${shots.length} fictional Lineage screenshots.`);
