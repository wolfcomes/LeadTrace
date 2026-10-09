/** Reproducible real-UI screenshots with fictional, browser-intercepted data only.
 * Start Vite locally, then: node leadtrace/ops/reviewer/capture_guide.mjs
 * No credentials, live API, source PDFs, or database are used.
 */
import {chromium} from '../../frontend/node_modules/playwright/index.mjs';
import {mkdirSync,writeFileSync,readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const base=process.env.GUIDE_UI_ORIGIN||'http://127.0.0.1:5186';
assert.equal(new URL(base).hostname,'127.0.0.1','Capture must use a local frontend');
const out=fileURLToPath(new URL('../../frontend/public/reviewer-guide/images/',import.meta.url));mkdirSync(out,{recursive:true});
const id=n=>`91000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const paper=id(1),wid=id(2),lid=id(3),version=1,sha='b'.repeat(64);
const browser=await chromium.launch({headless:true});const report=[];
try{for(const lang of ['zh','en']){
 const zh=lang==='zh',tr=(a,b)=>zh?a:b;
 const context=await browser.newContext({viewport:{width:1360,height:1000},deviceScaleFactor:1});
 const page=await context.newPage(),errors=[],unknown=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});page.on('console',m=>{if(m.type()==='error')console.error(m.text());});
 const compounds=['7a','7b','7c','6','Q'].map((label,i)=>({id:id(100+i),paper_id:paper,workspace_id:wid,compound_label:label,display_name:tr('教学示例 · ','Teaching example · ')+['Me','OMe','F',tr('中间体','intermediate'),tr('对照','control')][i],description:tr('完全虚构的操作练习；不是论文数据。','Fictional training fixture; not paper data.'),review_hint:i===1?tr('示例疑点：核对 OMe 的连接原子和取代位置。','Example issue: check OMe attachment and substitution position.'):null,sort_order:i,created_by_kind:'ai'}));
 const members=compounds.slice(0,3).map((c,i)=>({id:id(200+i),paper_id:paper,workspace_id:wid,lineage_id:lid,compound_id:c.id,role:i===0?'root':'terminal',sort_order:i}));
 const edges=[1,2].map((j,i)=>({id:id(300+i),paper_id:paper,workspace_id:wid,lineage_id:lid,parent_compound_id:compounds[0].id,child_compound_id:compounds[j].id,relation_type:'lead_optimization',modification_summary:tr(`教学示例：以 7a 为参考，将 Me 替换为 ${j===1?'OMe':'F'}；同一 assay 比较。`,`Teaching example: compare Me → ${j===1?'OMe':'F'} against 7a in the same assay.`),review_status:'draft',sort_order:i}));
 const lineage={id:lid,paper_id:paper,workspace_id:wid,lineage_label:tr('教学 SAR · 对位取代基比较','Training SAR · para-substituent comparison'),lineage_type:'sar',description:tr('虚构示例：7a 是共同参考物；箭头表示结构比较，不表示合成。','Fictional example: 7a is the common reference; edges are structural comparisons, not synthesis.'),sort_order:0,members,edges};
 const evidence={id:id(400),paper_id:paper,workspace_id:wid,kind:'text',source_sha256:sha,page_number:2,bbox:null,quoted_text:'TRAINING ONLY: 7b was compared with 7a in the same biochemical assay. This is a fictional source sentence.',caption:tr('虚构 Table 1 · 教学用出处','Fictional Table 1 · training source'),crop_asset_id:null,reviewer_note:tr('教学数据；不对应任何真实论文。','Training data; no real paper is represented.')};
 const ws={id:wid,review_task_id:id(4),assigned_reviewer_id:id(5),state:'editing',version,task_status:'assigned',bibliography:{paper_id:paper,paper_key:'TRAINING-ONLY · FICTIONAL DATA',title:tr('教学示例：从 Compound 到 Lineage 的审核练习','Training example: reviewing Compounds and Lineages'),journal:tr('虚构教学材料，不是已审核论文','Fictional training material, not an approved paper'),publication_year:2026,volume:'1',issue:'1',doi:null,abstract:tr('这是一份操作教学示例。学习核对编号、结构、测定、关系与来源，再进行人工确认。图中数据不代表任何真实研究结论。','This fictional example teaches source labels, structures, measurements, relationships and evidence before human confirmation. No displayed data represents a real research finding.'),abstract_source:tr('虚构示例文字','Fictional sample text'),pdb_references:[]},source:{asset_id:id(6),source_root_key:'source_pdfs',source_key:'training-only.pdf',sha256:sha,page_count:3},sections:['bibliography','compounds','structures','lineages','edge_evidence','activities'].map(section_key=>({section_key,state:'pending',note:null}))};
 const progress=()=>({workspace_id:wid,workspace_version:version,tracking_started:false,items:[...compounds.map(c=>({kind:'compound',entity_id:c.id,section_key:'compounds',label:c.compound_label,signature:sha,viewed:false})),{kind:'lineage',entity_id:lid,section_key:'lineages',label:lineage.lineage_label,signature:sha,viewed:false}],sections:[{section_key:'compounds',total:5,viewed:0,complete:false,state:'pending',note:null},{section_key:'lineages',total:1,viewed:0,complete:false,state:'pending',note:null}]});
 const list=items=>({workspace_id:wid,workspace_version:version,items,total:items.length});
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  const reply=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if(path==='/api/preview/environment')return reply({environment:'preview',instance_id:'training-only'});
  if(path.endsWith('/structure/depiction')){const c=compounds.find(c=>c.id===path.split('/').at(-3));return route.fulfill({contentType:'image/svg+xml',body:readFileSync(new URL(`./fixtures/${c.compound_label}.svg`,import.meta.url),'utf8')});}
  if(path==='/api/v1/auth/session')return reply({user:{username:'training-reviewer',display_name:tr('教学 Reviewer','Training Reviewer'),role:'reviewer',must_change_password:false},csrf_token:'fictional-local-token'});
  if(path.endsWith('/review-progress')||path.endsWith('/views'))return reply(progress());
  if(path.endsWith('/compound-highlights'))return reply(list([]));
  if(path.endsWith('/submission-validation'))return reply({valid:false,blockers:[{code:'STRUCTURE_REVIEW_REQUIRED',message:tr('教学待办：Compound 7b 的结构尚待核对，请对照来源后选择处理状态。','Training task: verify Compound 7b against its source before choosing a structure disposition.'),entity_type:'compound',entity_id:compounds[1].id,section_key:'structures'}]});
  if(path.includes('/layouts/'))return reply({revision:0,mode:path.split('/').at(-1),positions:{[compounds[0].id]:{x:80,y:150},[compounds[1].id]:{x:340,y:65},[compounds[2].id]:{x:340,y:235}},edge_controls:{}});
  if(path.endsWith('/compounds'))return reply(list(compounds));
  if(path.endsWith('/lineages'))return reply(list([lineage]));
  if(path.endsWith('/evidence-links'))return reply({workspace_version:version,items:[],total:0,edge_id:path.split('/').at(-2)});
  if(path.endsWith('/evidence'))return reply(list([evidence]));
  if(path.endsWith('/source-images'))return reply({compound_id:path.split('/').at(-2),workspace_version:version,items:[],total:0});
  if(path.endsWith('/structure')){const cid=path.split('/').at(-2),idx=compounds.findIndex(c=>c.id===cid);const smiles=['Nc1ccc(C)cc1','Nc1ccc(OC)cc1','Nc1ccc(F)cc1','Nc1ccc(O)cc1','c1ccccc1'][idx];return reply({workspace_version:version,structure:{id:id(500+idx),paper_id:paper,workspace_id:wid,compound_id:cid,smiles,canonical_smiles:smiles,molfile:null,inchi:null,inchikey:null,depiction_asset_id:id(800+idx),status:'draft',input_method:'manual_smiles'}});}
  if(path.endsWith('/activities')){const cid=path.split('/').at(-2);return reply({compound_id:cid,workspace_version:version,items:[{id:id(600+compounds.findIndex(c=>c.id===cid)),paper_id:paper,workspace_id:wid,compound_id:cid,evidence_id:evidence.id,assay_name:'human enzyme X inhibition',metric:'IC50',operator:'<',value:'10',unit:'nM',context:tr('虚构示例：生化实验；ATP 10 μM；脚注 a。','Fictional example: biochemical assay; ATP 10 μM; footnote a.'),sort_order:0}],total:1});}
  if(path===`/api/v2/workspaces/${wid}`)return reply(ws);
  unknown.push(path);console.error('Unmocked API',path);return reply({},404);
 });
 await page.goto(`${base}/review/papers/${paper}?workspace=${wid}`);await page.locator('[data-language-switch]').selectOption(zh?'zh-CN':'en');
 async function shot(name,selector){const el=page.locator(selector);await el.waitFor();assert.equal(await page.locator('[role=alert]').count(),0);assert.ok(!/could not be loaded|暂时无法读取|查看进度读取失败|读取查看进度失败|无法载入/i.test(await page.locator('body').innerText()),'Unexpected fixture loading failure');await el.scrollIntoViewIfNeeded();await page.evaluate(()=>document.fonts.ready);await el.evaluate(async el=>{await Promise.all([...el.querySelectorAll('img')].map(img=>img.decode().catch(()=>{})));});await el.screenshot({path:out+`${name}.${lang}.png`,animations:'disabled',style:'.topbar,.paper-workspace-tabs,.lineage-view-tabs,.compound-list-panel,.language-toolbar,.preview-environment{position:static!important}'});report.push({name,lang});}
 await shot('overview','[data-paper-workspace]');
 await page.locator('[data-workspace-tab]').nth(1).click();await page.locator('[data-compound-row]').nth(1).locator('button').first().click();await page.locator('[data-smiles-input]').waitFor();
 await shot('compound','[data-compound-list]');
 await page.locator('[data-add-activity]').click();const form=page.locator('.activity-create-form');await form.getByLabel('Assay',{exact:true}).fill('human enzyme X inhibition');await form.locator('select').nth(0).selectOption('<');await form.getByLabel('Value',{exact:true}).fill('10');await form.getByLabel('Unit',{exact:true}).fill('nM');await form.locator('select').nth(1).selectOption(evidence.id);await form.getByLabel('Context',{exact:true}).fill(tr('虚构示例：ATP 10 μM；Table 1，脚注 a。','Fictional example: ATP 10 μM; Table 1, footnote a.'));
 await shot('activity','.activity-editor');
 await page.locator('[data-workspace-tab]').nth(2).click();await page.locator('[data-lineage-graph]').waitFor();await page.locator('[data-lineage-graph]').evaluate(el=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await shot('lineage','.lineage-workspace');
 await page.locator('[data-graph-add-node]').click();await shot('node','[data-graph-compound-picker]');await page.locator('[data-cancel-graph-node]').click();
 await page.locator('[data-lineage-view-tab="edges"]').click();await shot('edge','.lineage-detail-panel');
 await page.locator('[data-workspace-tab]').nth(3).click();await page.locator('[data-submission-blocker]').waitFor();await shot('submit','.submission-checklist');
 assert.deepEqual(errors,[]);assert.deepEqual(unknown,[]);await context.close();
}}
finally{await browser.close();}
writeFileSync(out+'capture-manifest.json',JSON.stringify({kind:'real UI with fictional intercepted data',live_database_access:false,source_pdf_access:false,shots:report},null,2)+'\n');console.log(`Captured ${report.length} teaching screenshots.`);
