import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { defineComponent, nextTick } from 'vue';
import { afterEach, expect, it, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import type { Compound, PaperWorkspace } from '../src/v2/types';
vi.mock('../src/v2/api', async importOriginal => ({
  ...await importOriginal<typeof import('../src/v2/api')>(),
  getCompoundStructure: vi.fn(async () => ({ structure: null, workspace_version: 1 })),
}));
import CompoundStructureEditor from '../src/review/paper/CompoundStructureEditor.vue';
afterEach(() => setLocale('zh-CN'));
it('translates stored Ketcher child fallback messages in the parent without remounting the editor', async () => {
  const editor = defineComponent({ emits: ['error'], template: '<button data-child-error @click="$emit(\'error\', \'Ketcher 编辑器发生错误。\')">Child error</button>' });
  const wrapper = mount(CompoundStructureEditor, {
    props: { compound: { id: 'a', compound_label: '24' } as Compound, workspaceVersion: 1, source: { page_count: 4 } as PaperWorkspace['source'] },
    global: { plugins: [createPinia()], stubs: { KetcherEditor: editor, StructureSourceImages: true } },
  });
  await flushPromises(); await wrapper.get('[data-open-ketcher]').trigger('click');
  await wrapper.get('[data-child-error]').trigger('click');
  const child = wrapper.get('[data-child-error]').element;
  expect(wrapper.get('[role="alert"]').text()).toBe('Ketcher 编辑器发生错误。');
  setLocale('en'); await nextTick();
  expect(wrapper.get('[role="alert"]').text()).toBe('An error occurred in Ketcher.');
  expect(wrapper.get('[data-child-error]').element).toBe(child);
  expect(wrapper.emitted('mutated')).toBeUndefined();
  wrapper.unmount();
});
