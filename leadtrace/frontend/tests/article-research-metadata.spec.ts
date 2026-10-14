import { mount } from '@vue/test-utils';
import { expect, it } from 'vitest';
import ArticleMetadata from '../src/review/paper/ArticleMetadata.vue';
import { paperWorkspaceSchema } from '../src/v2/types';
import { workspace } from './paper-science-v2-fixtures';
import { setLocale } from '../src/i18n';
const metadata = {
  pmid: '12345678', pmcid: 'PMC1234567', identifiers_source: 'PubMed DOI match',
  abstract: 'Original abstract', abstract_source: 'Page 1', abstract_status: 'extracted' as const,
  research_profile: {
    molecular_forms: [{label:'Macrocycle',source:'Page 2'}],
    optimization_goals: [{label:'Brain penetration',source:'Page 3'}],
    targets: [{name:'Target A', role:'primary' as const, gene_symbol:'GENEA',organism:'Homo sapiens',source:'Page 1'},
      {name:'Target B',role:'selectivity' as const,source:'Table 2',review_hint:'Check species'}],
  },
};
it('preserves structured article metadata when decoding the workspace response', () => {
  const ws=workspace();
  const parsed=paperWorkspaceSchema.parse({...ws,bibliography:{...ws.bibliography,...metadata}});
  expect(parsed.bibliography).toMatchObject(metadata);
});
it('shows identifier links, abstract check status, source-backed tags and target roles', () => {
  setLocale('zh-CN');
  const wrapper=mount(ArticleMetadata,{props:{metadata}});
  expect(wrapper.get('[data-pmid-link]').attributes('href')).toBe('https://pubmed.ncbi.nlm.nih.gov/12345678/');
  for(const text of ['主要靶点','选择性对照','Homo sapiens','Brain penetration','Page 3']) expect(wrapper.text()).toContain(text);
});
it('distinguishes unrecorded abstracts from a checked absence and preserves its explanation', () => {
  setLocale('zh-CN');
  const wrapper=mount(ArticleMetadata,{props:{metadata:{abstract_status:'not_found',abstract_note:'Checked authorized main article; no abstract found'}}});
  expect(wrapper.text()).toContain('已检查，未找到');
  expect(wrapper.text()).toContain('Checked authorized main article');
  expect(wrapper.text()).not.toContain('尚未记录摘要');
});

it('keeps unchanged profile groups folded and compares the changed group in paired article records', async () => {
  const {default:SubmissionComparison}=await import('../src/approvals/SubmissionComparison.vue');
  const {frozenSnapshot,publicationIds}=await import('./paper-publication-v2-fixtures');
  const before=structuredClone(frozenSnapshot) as any, after=structuredClone(frozenSnapshot) as any;
  before.paper.research_profile=structuredClone(metadata.research_profile);
  after.paper.research_profile=structuredClone(metadata.research_profile);
  after.paper.research_profile.optimization_goals[0].label='Oral bioavailability';
  const wrapper=mount(SubmissionComparison,{props:{paperId:publicationIds.paper,snapshot:after,comparison:{kind:'previous_submission',baseline_submission_number:1,baseline_snapshot:before,events:[],warnings:[]}}});
  await wrapper.get('[data-record-tab="article"]').trigger('click');
  for(const side of ['before','after']) {
    const panel=wrapper.get(`[data-record-side="${side}"]`);
    expect(panel.get('[data-profile-diff-group="optimization_goals"]').attributes('open')).toBeDefined();
    expect(panel.get('[data-profile-diff-group="targets"]').attributes('open')).toBeUndefined();
    expect(panel.find('[data-profile-diff-group="molecular_forms"]').exists()).toBe(false);
  }
  expect(wrapper.get('[data-record-side="before"]').text()).toContain('Brain penetration');
  expect(wrapper.get('[data-record-side="after"]').text()).toContain('Oral bioavailability');
});

it('does not mislabel legacy recorded abstracts when the migrated response supplies not_checked',()=>{
  setLocale('zh-CN');
  const wrapper=mount(ArticleMetadata,{props:{metadata:{abstract:'Existing source text',abstract_status:'not_checked'}}});
  expect(wrapper.find('[data-abstract-status]').exists()).toBe(false);
});

it.each(['added','removed'])('shows both sides when a research profile is entirely %s',async(kind)=>{
  const {default:SubmissionComparison}=await import('../src/approvals/SubmissionComparison.vue');
  const {frozenSnapshot,publicationIds}=await import('./paper-publication-v2-fixtures');
  const before=structuredClone(frozenSnapshot) as any,after=structuredClone(frozenSnapshot) as any;
  (kind==='added'?after:before).paper.research_profile=structuredClone(metadata.research_profile);
  const wrapper=mount(SubmissionComparison,{props:{paperId:publicationIds.paper,snapshot:after,comparison:{kind:'previous_submission',baseline_submission_number:1,baseline_snapshot:before,events:[],warnings:[]}}});
  await wrapper.get('[data-record-tab="article"]').trigger('click');
  for(const side of ['before','after'])expect(wrapper.get(`[data-record-side="${side}"]`).find('[data-profile-diff-group="targets"]').exists()).toBe(true);
  expect(wrapper.get(`[data-record-side="${kind==='added'?'before':'after'}"] [data-profile-diff-group="targets"]`).text()).toContain('未记录');
});


it('keeps routine abstract provenance and obsolete molecular forms out of reading',()=>{
  const wrapper=mount(ArticleMetadata,{props:{metadata:{...metadata,abstract_note:'Routine audit explanation'}}});
  expect(wrapper.text()).not.toContain('Routine audit explanation');
  expect(wrapper.text()).not.toContain('PubMed DOI match');
  expect(wrapper.text()).not.toContain('摘要来源');
  expect(wrapper.find('[data-profile-group="molecular_forms"]').exists()).toBe(false);
  expect(wrapper.get('[data-profile-group="optimization_goals"] details').attributes('open')).toBeUndefined();
});
it('offers fixed modality selections and preserves legacy payloads during unrelated edits',async()=>{
  const {default:Editor}=await import('../src/review/paper/ResearchProfileEditor.vue');
  const profile={molecular_forms:[{label:'Macrocycle',source:'Legacy source'}],modalities:[{label:'抗芽孢形成剂',source:'Page 4'}],mechanisms:[]};
  const wrapper=mount(Editor,{props:{modelValue:profile}});
  expect(wrapper.find('[data-edit-group="molecular_forms"]').exists()).toBe(false);
  expect(wrapper.find('[data-edit-group="modalities"] input[data-term-label]').exists()).toBe(false);
  expect(wrapper.findAll('[data-modality-choice]').map(x=>x.attributes('value'))).toEqual(['直接靶点调节','PROTAC','分子胶','前药','其他','待明确']);
  expect(wrapper.text()).toContain('抗芽孢形成剂');
  await wrapper.get('[data-add-term="mechanisms"]').trigger('click');
  expect(wrapper.emitted('update:modelValue')?.[0]?.[0]).toMatchObject({molecular_forms:profile.molecular_forms,modalities:profile.modalities});
  await wrapper.get('[data-modality-choice][value="PROTAC"]').setValue(true);
  expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({modalities:[profile.modalities[0],{label:'PROTAC',source:''}]});
});
it('opens only changed evidence and preserves target order across paired records',async()=>{
  const {default:View}=await import('../src/approvals/ResearchProfileComparison.vue');
  const profile={targets:[{name:'Comparator',role:'selectivity' as const,source:'Same'},{name:'Main',role:'primary' as const,source:'Updated',review_hint:'Check identity'}]};
  const other={targets:[{...profile.targets[0]},{...profile.targets[1],role:'selectivity' as const,source:'Original',review_hint:null}]};
  const wrapper=mount(View,{props:{profile,other,available:true}});
  const details=wrapper.findAll('[data-target-evidence]');
  expect(details).toHaveLength(2);
  expect(details[0].attributes('open')).toBeUndefined();
  expect(details[1].attributes('open')).toBeDefined();
  expect(wrapper.findAll('[data-target-card] strong').map(x=>x.text())).toEqual(['Comparator','Main']);
});
it('opens enclosing editor disclosures for an invalid required source',async()=>{
  const {default:Editor}=await import('../src/review/paper/ResearchProfileEditor.vue');
  const wrapper=mount(Editor,{props:{modelValue:{mechanisms:[{label:'Inhibitor',source:''}]}}});
  await wrapper.get('[data-term-source]').trigger('invalid');
  expect(wrapper.get('[data-edit-group="mechanisms"]').attributes('open')).toBeDefined();
  expect(wrapper.get('[data-term-source]').element.closest('details')?.open).toBe(true);
});

it('keeps admin provenance in a dedicated folded disclosure while retaining actionable abstract issues',async()=>{
  const {default:SubmissionComparison}=await import('../src/approvals/SubmissionComparison.vue');
  const {frozenSnapshot,publicationIds}=await import('./paper-publication-v2-fixtures');
  const before=structuredClone(frozenSnapshot) as any,after=structuredClone(frozenSnapshot) as any;
  Object.assign(after.paper,{abstract_source:'Europe PMC record',identifiers_source:'DOI match',abstract_status:'extracted',abstract_note:'Routine explanation'});
  const wrapper=mount(SubmissionComparison,{props:{paperId:publicationIds.paper,snapshot:after,comparison:{kind:'previous_submission',baseline_submission_number:1,baseline_snapshot:before,events:[],warnings:[]}}});
  await wrapper.get('[data-record-tab="article"]').trigger('click');
  const panel=wrapper.get('[data-record-side="after"]');
  const audit=panel.get('[data-article-provenance]');
  expect(audit.attributes('open')).toBeUndefined();
  expect(audit.text()).toContain('Europe PMC record');
  for(const field of panel.findAll('.article-details'))expect(field.text()).not.toContain('Routine explanation');
});
it('requires explanations for new other or unresolved modalities',async()=>{
  const {default:Editor}=await import('../src/review/paper/ResearchProfileEditor.vue');
  const wrapper=mount(Editor,{props:{modelValue:{modalities:[]}}});
  await wrapper.get('[data-modality-choice][value="其他"]').setValue(true);
  await wrapper.setProps({modelValue:wrapper.emitted('update:modelValue')!.at(-1)![0] as any});
  expect(wrapper.get('[data-term-hint]').attributes('required')).toBeDefined();
});
it('shows canonical display labels while preserving qualified legacy wording in evidence',async()=>{
  const {default:View}=await import('../src/review/paper/ResearchProfile.vue');
  const profile={modalities:[{label:'前药特征（43自身亦有活性）',source:'Discussion'}]};
  const wrapper=mount(View,{props:{profile}});
  expect(wrapper.get('strong').text()).toBe('前药');
  expect(wrapper.get('details').text()).toContain('前药特征（43自身亦有活性）');
  expect(profile.modalities[0].label).toBe('前药特征（43自身亦有活性）');
});

it.each(['insert','remove','reorder'])('does not unfold unchanged target evidence after %s',async(change)=>{
 const {default:View}=await import('../src/approvals/ResearchProfileComparison.vue');
 const a={name:'A',role:'primary' as const,source:'Page 1'},b={name:'B',role:'selectivity' as const,source:'Page 2'},c={name:'C',role:'mechanistic' as const,source:'Page 3'};
 const other={targets:[a,b]},profile={targets:change==='insert'?[c,a,b]:change==='remove'?[b]:[b,a]};
 const wrapper=mount(View,{props:{profile,other,available:true}});
 for(const card of wrapper.findAll('[data-target-card]'))if(['A','B'].includes(card.get('strong').text()))expect(card.get('[data-target-evidence]').attributes('open')).toBeUndefined();
});
it('opens removed identifiers on both sides of a target pair',async()=>{
 const {default:View}=await import('../src/approvals/ResearchProfileComparison.vue');
 const target={name:'A',role:'primary' as const,source:'Page 1'};
 for(const [profile,other] of [[{targets:[target]},{targets:[{...target,uniprot_id:'P12345'}]}],[{targets:[{...target,uniprot_id:'P12345'}]},{targets:[target]}]]){
  const wrapper=mount(View,{props:{profile,other,available:true}});
  expect(wrapper.get('[data-target-evidence]').attributes('open')).toBeDefined();
 }
});

it('pairs terms across insertion and unfolds a source edit on both sides only',async()=>{
 const {default:View}=await import('../src/approvals/ResearchProfileComparison.vue');
 const before={mechanisms:[{label:'Inhibitor',source:'Original'},{label:'Reversible',source:'Page 2'}]},after={mechanisms:[{label:'Allosteric',source:'Page 3'},{label:'Inhibitor',source:'Corrected'},{label:'Reversible',source:'Page 2'}]};
 for(const side of ['before','after'] as const){
  const wrapper=mount(View,{props:{profile:side==='before'?before:after,other:side==='before'?after:before,side,available:true}});
  const pairs=wrapper.findAll('[data-profile-pair]');
  expect(pairs).toHaveLength(3);
  expect(pairs[1].get('strong').text()).toBe('Inhibitor');
  expect(pairs[1].get('[data-term-evidence]').attributes('open')).toBeDefined();
  expect(pairs[2].get('[data-term-evidence]').attributes('open')).toBeUndefined();
 }
});

it('keeps newly added article profile evidence folded while showing the new groups',async()=>{
 const {default:View}=await import('../src/approvals/ResearchProfileComparison.vue');
 const wrapper=mount(View,{props:{profile:{targets:[{name:'A',role:'primary',source:'New source'}],mechanisms:[{label:'Inhibitor',source:'New source'}]},other:{},available:true}});
 for(const details of wrapper.findAll('[data-target-evidence],[data-term-evidence]'))expect(details.attributes('open')).toBeUndefined();
 for(const group of wrapper.findAll('[data-profile-diff-group]'))expect(group.attributes('open')).toBeDefined();
});

it('keeps unrelated replacement targets separate with both evidence panels folded',async()=>{
 const {default:View}=await import('../src/approvals/ResearchProfileComparison.vue');
 const before={targets:[{name:'Target A',role:'primary' as const,source:'Source A'}]},after={targets:[{name:'Target B',role:'primary' as const,source:'Source B'}]};
 for(const side of ['before','after'] as const){
  const wrapper=mount(View,{props:{profile:side==='before'?before:after,other:side==='before'?after:before,side,available:true}});
  expect(wrapper.findAll('[data-profile-pair]')).toHaveLength(2);
  expect(wrapper.get('[data-target-evidence]').attributes('open')).toBeUndefined();
 }
});
it('pairs unchanged duplicate entries once each without inventing additions and removals',async()=>{
 const {default:View}=await import('../src/approvals/ResearchProfileComparison.vue');
 const term={label:'Potency',source:'Page 1'},profile={optimization_goals:[term,{...term}]};
 for(const side of ['before','after'] as const){
  const wrapper=mount(View,{props:{profile,other:structuredClone(profile),side,available:true}});
  expect(wrapper.findAll('[data-profile-pair]')).toHaveLength(2);
  expect(wrapper.findAll('strong').map(x=>x.text())).toEqual(['Potency','Potency']);
  expect(wrapper.text()).not.toContain('未记录');
  for(const evidence of wrapper.findAll('[data-term-evidence]'))expect(evidence.attributes('open')).toBeUndefined();
 }
});

it('arranges six article modules and keeps exact quotations separate from explanations', () => {
  const quote = {source_kind:'main_pdf' as const,quoted_text:'Exact paper sentence.',page_number:2};
  const wrapper=mount(ArticleMetadata,{props:{metadata:{...metadata,research_profile:{...metadata.research_profile,mechanisms:[{label:'Inhibitor',source:'Human explanation',evidence:[quote]}]}}}});
  expect(wrapper.findAll('[data-article-module]')).toHaveLength(6);
  expect(wrapper.get('[data-profile-group=mechanisms] blockquote').text()).toBe('Exact paper sentence.');
  expect(wrapper.get('[data-profile-group=mechanisms]').text()).toContain('Human explanation');
  expect(wrapper.get('[data-profile-group=targets]').text()).toContain('尚未补充原文摘录');
});

it('recognizes evidence-only changes without treating identical copied evidence as changed', async () => {
  const {profileEvidenceChanged,pairProfileEntries}=await import('../src/approvals/researchProfilePairs');
  const entry={label:'A',source:'Page 1',evidence:[{source_kind:'main_pdf' as const,quoted_text:'Original',page_number:1}]};
  expect(profileEvidenceChanged({before:entry,after:structuredClone(entry)})).toBe(false);
  const changed=structuredClone(entry);changed.evidence[0]!.quoted_text='Corrected';
  expect(profileEvidenceChanged({before:entry,after:changed})).toBe(true);
  expect(pairProfileEntries([entry,entry],[structuredClone(entry),structuredClone(entry)])).toHaveLength(2);
});

it('links supplement evidence to its own source and never to main PDF; crops stay lazy',async()=>{
  const {default:Evidence}=await import('../src/review/paper/ArticleEvidence.vue');
  const wrapper=mount(Evidence,{props:{sourceContext:{paperId:'paper',pageCount:5,sha256:'a'.repeat(64)},evidence:[{source_kind:'supplement',quoted_text:'Supporting text',page_number:2,locator:'Supplement S1',source_url:'https://example.org/si.pdf'},{source_kind:'main_pdf',quoted_text:'Main text',page_number:1,source_sha256:'a'.repeat(64),bbox:{x:0,y:0,width:.5,height:.2}}]}});
  expect(wrapper.findAll('[data-article-source-link]')).toHaveLength(1);
  expect(wrapper.find('a[href="https://example.org/si.pdf"]').exists()).toBe(true);
  expect(wrapper.findComponent({name:'FrozenPdfCrop'}).exists()).toBe(false);
  expect(wrapper.find('[data-article-crop]').exists()).toBe(true);
  await wrapper.setProps({sourceContext:{paperId:'paper',pageCount:5,sha256:'b'.repeat(64)}});
  expect(wrapper.find('[data-article-crop]').exists()).toBe(false);
});

it('shows changed PDB evidence as readable quotations in both approval sides',async()=>{
  const {default:SubmissionComparison}=await import('../src/approvals/SubmissionComparison.vue');
  const {frozenSnapshot,publicationIds}=await import('./paper-publication-v2-fixtures');
  const before=structuredClone(frozenSnapshot) as any,after=structuredClone(frozenSnapshot) as any;
  before.paper.pdb_references=[{pdb_id:'1ABC',usage:'cited_structure',source_context:'Existing explanation'}];
  after.paper.pdb_references=structuredClone(before.paper.pdb_references);after.paper.pdb_references[0].evidence=[{source_kind:'main_pdf',quoted_text:'Exact structure evidence',page_number:1}];
  const wrapper=mount(SubmissionComparison,{props:{paperId:publicationIds.paper,snapshot:after,comparison:{kind:'previous_submission',baseline_submission_number:1,baseline_snapshot:before,events:[],warnings:[]}}});
  await wrapper.get('[data-record-tab=article]').trigger('click');
  expect(wrapper.get('[data-record-side=after] [data-pdb-comparison] blockquote').text()).toBe('Exact structure evidence');
  expect(wrapper.get('[data-record-side=before] [data-pdb-comparison]').text()).toContain('尚未补充原文摘录');
});

it('renders a paired PDB placeholder when a historical snapshot has no PDB field',async()=>{
  const {default:SubmissionComparison}=await import('../src/approvals/SubmissionComparison.vue');
  const {frozenSnapshot,publicationIds}=await import('./paper-publication-v2-fixtures');
  const before=structuredClone(frozenSnapshot) as any,after=structuredClone(frozenSnapshot) as any;
  delete before.paper.pdb_references;
  after.paper.pdb_references=[{pdb_id:'1ABC',usage:'cited_structure',evidence:[{source_kind:'main_pdf',quoted_text:'Original structure text',page_number:1}]}];
  const wrapper=mount(SubmissionComparison,{props:{paperId:publicationIds.paper,snapshot:after,comparison:{kind:'previous_submission',baseline_submission_number:1,baseline_snapshot:before,events:[],warnings:[]}}});
  await wrapper.get('[data-record-tab=article]').trigger('click');
  expect(wrapper.get('[data-record-side=before] [data-pdb-comparison]').text()).toContain('未记录');
  expect(wrapper.get('[data-record-side=after] [data-pdb-comparison]').text()).toContain('1ABC');
});
