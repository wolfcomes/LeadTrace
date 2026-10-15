import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { expect, it, vi } from 'vitest';
import BibliographyEditor from '../src/review/paper/BibliographyEditor.vue';
import { workspace } from './paper-science-v2-fixtures';
import { paperWorkspaceSchema } from '../src/v2/types';
import { setLocale } from '../src/i18n';

it.each([
 ['Select at least one primary molecule type','分子类型未保存：非空分类至少选择一项主要类型。'],
 ['Duplicate molecule type labels are not allowed','分子类型未保存：同一类型不能重复选择，请合并或删除重复条目。'],
])('shows actionable classification validation and retains input: %s',async(message,expected)=>{
 setLocale('zh-CN');
 const request=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({code:'INVALID_ARTICLE_METADATA',message,request_id:'synthetic'}),{status:422}));
 const wrapper=mount(BibliographyEditor,{props:{workspace:paperWorkspaceSchema.parse(workspace())},global:{plugins:[createPinia()]}});
 try {
  await wrapper.get('[data-edit-bibliography]').trigger('click');
  await wrapper.get('[data-abstract-input]').setValue('Retained draft abstract');
  await wrapper.get('form').trigger('submit');
  await flushPromises();
  expect(wrapper.get('[role=alert]').text()).toBe(expected);
  expect(wrapper.get<HTMLTextAreaElement>('[data-abstract-input]').element.value).toBe('Retained draft abstract');
 } finally {wrapper.unmount();request.mockRestore();}
});
