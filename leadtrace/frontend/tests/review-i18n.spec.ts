import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { afterEach, expect, it } from 'vitest';
import EdgeEditor from '../src/review/paper/EdgeEditor.vue';
import SectionStatusControl from '../src/review/paper/SectionStatusControl.vue';
import EvidenceExcerpt from '../src/review/paper/EvidenceExcerpt.vue';
import { setLocale } from '../src/i18n';
import type { Compound, Lineage, Evidence, PaperWorkspace } from '../src/v2/types';

afterEach(() => setLocale('zh-CN'));
it('switches actions in place while retaining an unsaved relationship and permissions', async () => {
  setLocale('zh-CN');
  const edge = { id: 'e', parent_compound_id: 'a', child_compound_id: 'b', relation_type: 'comparison', modification_summary: '原文科学描述', review_status: 'draft' };
  const lineage = { id: 'l', lineage_type: 'sar', members: [{ compound_id: 'a', role: 'root' }, { compound_id: 'b', role: 'unspecified' }], edges: [edge] } as Lineage;
  const compounds = [{ id: 'a', compound_label: '24' }, { id: 'b', compound_label: '55' }] as Compound[];
  const wrapper = mount(EdgeEditor, { props: { lineage, compounds } });
  await wrapper.get('[data-edit-edge]').trigger('click');
  await wrapper.get('[data-edit-edge-summary]').setValue('未保存的科学修订');
  const input = wrapper.get('[data-edit-edge-summary]').element;
  setLocale('en'); await nextTick();
  expect(wrapper.get('[data-save-edge-edit]').text()).toBe('Save edge');
  expect(wrapper.get('[data-edit-edge-summary]').element).toBe(input);
  expect((input as HTMLInputElement).value).toBe('未保存的科学修订');
  expect(wrapper.emitted('update')).toBeUndefined();
  await wrapper.get('[data-save-edge-edit]').trigger('click');
  expect(wrapper.emitted('update')?.[0]?.[1]).toMatchObject({ modificationSummary: '未保存的科学修订' });
  await wrapper.setProps({ readOnly: true });
  expect(wrapper.get('[data-edit-edge]').attributes('disabled')).toBeDefined();
  wrapper.unmount();
});
it('switches section labels and accessible names without a workspace mutation', async () => {
  const wrapper = mount(SectionStatusControl, { props: { section: { section_key: 'compounds', state: 'pending', note: null } } });
  setLocale('en'); await nextTick();
  expect(wrapper.text()).toContain('Compounds');
  expect(wrapper.get('[data-section-choice="completed"]').text()).toBe('Complete');
  expect(wrapper.get('[aria-label]').attributes('aria-label')).toBe('Compounds section status');
  expect(wrapper.emitted('change')).toBeUndefined();
  wrapper.unmount();
});
it('translates source navigation while preserving scientific content', async () => {
  setLocale('en');
  const evidence = { id: 'ev', kind: 'text', page_number: 4, quoted_text: '原文科学内容不得翻译', reviewer_note: '人工核对备注' } as Evidence;
  const wrapper = mount(EvidenceExcerpt, { props: { evidence, workspace: { bibliography: { paper_id: 'paper' }, source: { page_count: 10 } } as PaperWorkspace } });
  expect(wrapper.get('[data-evidence-pdf-locator]').text()).toBe('Source page 4 ↗');
  expect(wrapper.text()).toContain('原文科学内容不得翻译');
  expect(wrapper.text()).toContain('人工核对备注');
  wrapper.unmount();
});
