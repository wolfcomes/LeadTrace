import { defineComponent, ref } from 'vue';
import { mount } from '@vue/test-utils';
import { expect, it } from 'vitest';
import { providePendingEdits, usePendingEdit } from '../src/review/paper/usePendingEdits';

it('tracks pending state and removes it when editor unmounts',async()=>{
 const dirty=ref(false), visible=ref(true);
 const Child=defineComponent({setup(){usePendingEdit(()=>dirty.value);return()=>null;}});
 const Parent=defineComponent({components:{Child},setup(){const state=providePendingEdits();return {state,visible};},template:'<div><span>{{state.blocked.value}}</span><Child v-if="visible" /></div>'});
 const wrapper=mount(Parent);expect(wrapper.get('span').text()).toBe('false');
 dirty.value=true;await wrapper.vm.$nextTick();expect(wrapper.get('span').text()).toBe('true');
 dirty.value=false;await wrapper.vm.$nextTick();expect(wrapper.get('span').text()).toBe('false');
 dirty.value=true;visible.value=false;await wrapper.vm.$nextTick();await wrapper.vm.$nextTick();expect(wrapper.get('span').text()).toBe('false');
 wrapper.unmount();
});

import EdgeEditor from '../src/review/paper/EdgeEditor.vue';
import { compounds, lineages } from './paper-science-v2-fixtures';

it('protects changed edge endpoints without blocking the default form',async()=>{
 const Parent=defineComponent({components:{EdgeEditor},setup(){const state=providePendingEdits();return {state,lineage:lineages[0],compounds};},template:'<div><span data-pending>{{state.blocked.value}}</span><EdgeEditor :lineage="lineage" :compounds="compounds" /></div>'});
 const wrapper=mount(Parent);expect(wrapper.get('[data-pending]').text()).toBe('false');
 await wrapper.get('.edge-create-form select').setValue(compounds[1]!.id);
 expect(wrapper.get('[data-pending]').text()).toBe('true');
 await wrapper.get('[data-cancel-edge-create]').trigger('click');
 expect(wrapper.get('[data-pending]').text()).toBe('false');wrapper.unmount();
});
