import { afterEach, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { locale } from '../src/i18n';
import AiProvenance from '../src/review/paper/AiProvenance.vue';
afterEach(()=>{locale.value='zh-CN';});
const base={run_key:'test',stage:'prefill' as const,model:'deepseek-flash',reasoning_effort:'max',verification:'requested_only' as const,outcome:'needs_revision' as const,source_sha256:'a'.repeat(64),candidate_file_sha256:'b'.repeat(64),applied_workspace_version:2};
it('separates requested config from observed config and labels later edits',()=>{
 const w=mount(AiProvenance,{props:{records:[base],workspaceVersion:5}});
 expect(w.text()).toContain('deepseek-flash'); expect(w.text()).toContain('max');
 expect(w.text()).toContain('仅请求配置'); expect(w.text()).toContain('后续修改');
});
it('does not replace applied provenance with a review or an unused run',()=>{
 const w=mount(AiProvenance,{props:{compact:true,records:[base,{...base,run_key:'review',stage:'independent_review',model:'gpt-test',applied_workspace_version:null},{...base,run_key:'failed',model:'failed-model',outcome:'failed',applied_workspace_version:null}]}});
 expect(w.text()).toContain('deepseek-flash'); expect(w.text()).not.toContain('gpt-test'); expect(w.text()).not.toContain('failed-model');
});
it('handles unknown history and English without implying verification',()=>{
 locale.value='en';
 const w=mount(AiProvenance,{props:{records:[{...base,model:null,reasoning_effort:null,verification:'unknown'}]}});
 expect(w.text()).toContain('Not recorded'); expect(w.text()).not.toContain('仅请求');
});
