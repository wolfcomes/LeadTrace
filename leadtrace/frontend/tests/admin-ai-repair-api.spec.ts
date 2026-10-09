import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from '../src/auth/store';
import { acceptAiRepair, repairAiTask, aiReviewReportSchema } from '../src/admin/aiTasks';
const job = {id:'repair',paper_id:'paper',paper_key:'TEST',paper_title:'Test',workspace_id:'workspace',workspace_version:3,action:'repair',preset_id:'preset',model:'model',reasoning_effort:'high',state:'proposal_ready',delivery_state:'not_applied',stage:'proposal_ready',error_code:null,error_message:null,created_at:'2026-10-09',started_at:null,finished_at:null,heartbeat_at:null,timeout_seconds:3600,attempt:1,parent_job_id:'review',result_summary:{},can_cancel:false,can_retry:false,can_accept:true};
beforeEach(() => {setActivePinia(createPinia());useAuthStore().csrfToken='csrf-test';});
afterEach(() => vi.unstubAllGlobals());
it('sends separate CSRF-protected repair and hash-bound acceptance requests', async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify(job),{status:200,headers:{'Content-Type':'application/json'}}));
  vi.stubGlobal('fetch',fetch);
  const input={preset_id:'preset',reasoning_effort:'high',timeout_seconds:3600,idempotency_key:'unique'};
  expect((await repairAiTask('review/id',input)).action).toBe('repair');
  expect((await acceptAiRepair('repair/id','a'.repeat(64))).can_accept).toBe(true);
  expect(fetch.mock.calls).toHaveLength(2);
  const calls=fetch.mock.calls as unknown as [string, RequestInit][];
  expect(calls[0][0]).toBe('/api/v2/admin/ai-tasks/review%2Fid/repair');
  expect(calls[1][0]).toBe('/api/v2/admin/ai-tasks/repair%2Fid/accept');
  expect(JSON.parse(calls[0][1].body as string)).toEqual(input);
  expect(JSON.parse(calls[1][1].body as string)).toEqual({proposal_sha256:'a'.repeat(64)});
  for(const [, options] of calls) {
    expect(options.method).toBe('POST');
    expect(new Headers(options.headers).get('X-CSRF-Token')).toBe('csrf-test');
  }
});
it('retains aggregate statistics and concrete proposal payload through response parsing', () => {
  const overview={schema_version:1,basis:'producer',entities:[{domain:'compounds',total:3,supported:null,incorrect:null,uncertain:null,unreviewed:3,flagged:1}],compound_coverage:{known:false,covered:null,expected:null,percent:null},audit_coverage:{known:false,checked:0,expected:null,percent:null},issue_groups:[],highlights:[{code:'MISSING_STRUCTURE',ref:'compound:23',summary:'Structure missing'}],unique_crop_regions:3};
  const proposal={sha256:'a'.repeat(64),counts:{compounds:{added:0,updated:1,removed:0}},total_changes:1,changes:[{domain:'compounds',ref:'compound:23',action:'updated',before:{smiles:'C'},after:{smiles:'CC'}}],remaining_findings:0};
  const result=aiReviewReportSchema.parse({report_kind:'repair',job_id:'job',reviewed_workspace_version:3,coverage:{expected:0,reviewed:0,missing:[]},findings:[],overview,proposal});
  expect(result.overview).toEqual(overview);expect(result.proposal).toEqual(proposal);
});
