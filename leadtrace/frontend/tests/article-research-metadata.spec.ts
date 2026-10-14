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
  for(const text of ['主要靶点','选择性对照','Homo sapiens','Brain penetration','Page 3','已提取']) expect(wrapper.text()).toContain(text);
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
    expect(panel.get('[data-profile-diff-group="molecular_forms"]').attributes('open')).toBeUndefined();
  }
  expect(wrapper.get('[data-record-side="before"]').text()).toContain('Brain penetration');
  expect(wrapper.get('[data-record-side="after"]').text()).toContain('Oral bioavailability');
});

it('does not mislabel legacy recorded abstracts when the migrated response supplies not_checked',()=>{
  setLocale('zh-CN');
  const wrapper=mount(ArticleMetadata,{props:{metadata:{abstract:'Existing source text',abstract_status:'not_checked'}}});
  expect(wrapper.get('[data-abstract-status]').text()).toBe('已记录，检查状态未标注');
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
