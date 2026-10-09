import { afterEach, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { locale } from '../src/i18n';
import FieldExample from '../src/review/paper/FieldExample.vue';
import ReviewerHelp from '../src/review/paper/ReviewerHelp.vue';
afterEach(()=>{locale.value='zh-CN';});
it('keeps Activity help attached to its semantic chapter when the guide is expanded',()=>{
 const wrapper=mount(FieldExample,{props:{section:'activities'}});
 expect(wrapper.text()).toContain('Operator = <');
 wrapper.unmount();
});
it('links the full handbook in the chosen UI language without navigating the editor',async()=>{
 const wrapper=mount(ReviewerHelp);
 expect(wrapper.get('[data-reviewer-handbook]').attributes('href')).toBe('/reviewer-guide/zh.html');
 expect(wrapper.get('[data-reviewer-handbook]').attributes('target')).toBe('_blank');
 locale.value='en';await wrapper.vm.$nextTick();
 expect(wrapper.get('[data-reviewer-handbook]').attributes('href')).toBe('/reviewer-guide/en.html');
 wrapper.unmount();
});
