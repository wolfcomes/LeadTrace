import {mount} from '@vue/test-utils';
import {expect,it} from 'vitest';
import {buildRecordComparison} from '../src/approvals/recordComparison';
import {frozenPaperSnapshotSchema} from '../src/v2/types';
import SubmissionComparison from '../src/approvals/SubmissionComparison.vue';
import {frozenSnapshot,publicationIds as ids} from './paper-publication-v2-fixtures';
function pair(){
 const activity=frozenSnapshot.activities[0]!;
 const table={id:'50000000-0000-4000-8000-000000000099',paper_id:ids.paper,workspace_id:activity.workspace_id,name:'Table 1',kind:'source',source_label:'Table 1',source_title:'Potency',page_number:1,review_hint:null,review_status:'draft',created_by_kind:'ai',mode:'any',sort:'label',columns:[{id:'c',label:'Original heading',assay:activity.assay_name,metric:activity.metric,unit:activity.unit,activity_ids:[activity.id]}]};
 const before={...structuredClone(frozenSnapshot),activity_tables:[table]};
 const after=structuredClone(before);after.activity_tables[0]!.columns[0]!.label='Corrected heading';after.activity_tables[0]!.review_status='reviewer_confirmed';
 return {before,after};
}
it('accepts frozen tables and routes reviewer table edits into a separate comparison record',()=>{
 const {before,after}=pair();expect(frozenPaperSnapshotSchema.safeParse(after).success).toBe(true);
 const result=buildRecordComparison(after,{kind:'reviewer_start',baseline_submission_number:null,baseline_snapshot:before,events:[],warnings:[]});
 expect(result.tables).toHaveLength(1);expect(result.tables[0]!.changed).toBe(true);expect(result.article.changed).toBe(false);
 const confirmed=structuredClone(before);confirmed.activity_tables[0]!.review_status='reviewer_confirmed';
 const unchanged=buildRecordComparison(confirmed,{kind:'reviewer_start',baseline_submission_number:null,baseline_snapshot:before,events:[],warnings:[]});
 expect(unchanged.changes).toHaveLength(0);expect(unchanged.tables[0]!.changed).toBe(false);
});
it('shows frozen before/after table headings and referenced values without live reads',async()=>{
 const {before,after}=pair();const w=mount(SubmissionComparison,{props:{snapshot:after,paperId:ids.paper,comparison:{kind:'reviewer_start',baseline_submission_number:null,baseline_snapshot:before,events:[],warnings:[]}}});
 await w.get('[data-record-tab="tables"]').trigger('click');
 expect(w.get('[data-record-side="before"]').text()).toContain('Original heading');expect(w.get('[data-record-side="after"]').text()).toContain('Corrected heading');
 expect(w.get('[data-record-side="after"]').text()).toContain(String(after.activities[0]!.value));w.unmount();
});

it('attributes screenshot edits to their linked table and preserves explicit frozen row order',async()=>{
 const {before,after}=pair();
 Object.assign(before.activity_tables[0]!,{compound_ids:[before.compounds[1]!.id,before.compounds[0]!.id],evidence_ids:[before.evidence[0]!.id],sort:'default'});
 Object.assign(after.activity_tables[0]!,structuredClone(before.activity_tables[0]!));after.evidence[0]!.caption='Corrected source region';
 const result=buildRecordComparison(after,{kind:'reviewer_start',baseline_submission_number:null,baseline_snapshot:before,events:[],warnings:[]});
 expect(result.tables[0]!.changed).toBe(true);expect(result.tables[0]!.changes.some(c=>c.domain==='evidence')).toBe(true);expect(result.article.changed).toBe(false);
 const {default:FrozenActivityTable}=await import('../src/approvals/FrozenActivityTable.vue');
 const w=mount(FrozenActivityTable,{props:{table:after.activity_tables[0]!,snapshot:after,paperId:ids.paper}});
 expect(w.findAll('tbody th').map(x=>x.text())).toEqual([after.compounds[1]!.compound_label,after.compounds[0]!.compound_label]);w.unmount();
});
it('does not invent reviewer changes for absent versus empty optional table defaults',()=>{
 const {before,after}=pair();Object.assign(after.activity_tables[0]!,structuredClone(before.activity_tables[0]!),{compound_ids:null,evidence_ids:[]});
 const result=buildRecordComparison(after,{kind:'reviewer_start',baseline_submission_number:null,baseline_snapshot:before,events:[],warnings:[]});
 expect(result.tables[0]!.changed).toBe(false);
});
