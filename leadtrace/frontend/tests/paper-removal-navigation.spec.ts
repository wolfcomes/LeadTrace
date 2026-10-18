import { mount, flushPromises } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import { expect, it, vi } from 'vitest';
import Page from '../src/admin/PaperCatalogDetailPage.vue';
vi.mock('../src/v2/api',()=>({getAdminPaper:vi.fn(async()=>({id:'p1',paper_key:'LT-001',title:'Example',journal:'JMC',publication_year:2024,volume:'67',issue:'5',doi:null,review:null,source:{source_key:'example.pdf',page_count:3,byte_size:100,integrity_state:'verified'},catalog_state:'verified'}))}));
it('returns to the first catalog page with filters after removing from detail',async()=>{
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/papers/:paperId',component:Page},{path:'/catalog',name:'admin-papers',component:{template:'<div>Catalog</div>'}}]});
 await router.push('/papers/p1?page=2&issue=5');await router.isReady();
 const wrapper=mount(Page,{global:{plugins:[router],stubs:{AiTaskConsole:true,PaperRemovalDialog:{template:'<button data-confirm-stub @click="$emit(&quot;removed&quot;)">Remove</button>'}}}});
 await flushPromises();await wrapper.get('[data-remove-paper]').trigger('click');await wrapper.get('[data-confirm-stub]').trigger('click');await flushPromises();
 expect(router.currentRoute.value.name).toBe('admin-papers');expect(router.currentRoute.value.query).toEqual({page:'1',issue:'5'});wrapper.unmount();
});
