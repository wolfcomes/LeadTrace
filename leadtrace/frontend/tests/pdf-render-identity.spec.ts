import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PdfReviewCanvas from '../src/pdf-viewer/PdfReviewCanvas.vue';
const pdf = vi.hoisted(() => ({ getDocument: vi.fn() }));
vi.mock('pdfjs-dist', () => ({ getDocument: pdf.getDocument, GlobalWorkerOptions: {} }));
function deferred<T>() { let resolve!: (value:T)=>void; const promise=new Promise<T>(r=>{resolve=r;}); return {promise,resolve}; }
function page(width=800,height=400) { return {getViewport:()=>({width,height}),render:vi.fn(()=>({promise:Promise.resolve(),cancel:vi.fn()}))}; }
beforeEach(()=>{vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as any);});
afterEach(()=>vi.restoreAllMocks());
it('never displays an old page after a later page has finished, and blocks capture while loading', async()=>{
 const old=deferred<any>(); const p1=page(),p2=page(400,800);
 pdf.getDocument.mockReturnValue({promise:Promise.resolve({getPage:(n:number)=>n===1?old.promise:Promise.resolve(p2),destroy:vi.fn(()=>Promise.resolve())}),destroy:vi.fn(()=>Promise.resolve())});
 const wrapper=mount(PdfReviewCanvas,{props:{pdfUrl:'/synthetic.pdf',pageCount:2,regions:[],selectionMode:true}});await flushPromises();
 const surface=wrapper.get('[data-pdf-page]');
 await surface.trigger('pointerdown',{clientX:50,clientY:50});await surface.trigger('pointerup',{clientX:200,clientY:200});
 expect(wrapper.emitted('create-region')).toBeUndefined();
 await wrapper.setProps({page:2});await flushPromises();
 expect(wrapper.get('canvas').attributes('height')).toBe('800');
 old.resolve(p1);await flushPromises();
 expect(p1.render).not.toHaveBeenCalled();
 expect(wrapper.get('canvas').attributes('height')).toBe('800');
 wrapper.unmount();
});
it('discards an old document load after the source URL changes',async()=>{
 const old=deferred<any>();const stale=page(); const current=page(300,600);
 pdf.getDocument.mockImplementation(({url}:{url:string})=>({promise:url==='/old.pdf'?old.promise:Promise.resolve({getPage:()=>Promise.resolve(current),destroy:vi.fn(()=>Promise.resolve())}),destroy:vi.fn(()=>Promise.resolve())}));
 const wrapper=mount(PdfReviewCanvas,{props:{pdfUrl:'/old.pdf',pageCount:1,regions:[]}});await flushPromises();
 await wrapper.setProps({pdfUrl:'/new.pdf'});await flushPromises();
 old.resolve({getPage:()=>Promise.resolve(stale),destroy:vi.fn(()=>Promise.resolve())});await flushPromises();
 expect(stale.render).not.toHaveBeenCalled();expect(wrapper.get('canvas').attributes('width')).toBe('300');wrapper.unmount();
});
it('cancels a pending region when page identity changes and does not save pointer cancellations',async()=>{
 pdf.getDocument.mockReturnValue({promise:Promise.resolve({getPage:()=>Promise.resolve(page()),destroy:vi.fn(()=>Promise.resolve())}),destroy:vi.fn(()=>Promise.resolve())});
 const wrapper=mount(PdfReviewCanvas,{props:{pdfUrl:'/synthetic.pdf',pageCount:2,regions:[],selectionMode:true}});await flushPromises();
 const surface=wrapper.get('[data-pdf-page]');await surface.trigger('pointerdown',{clientX:50,clientY:50});
 await wrapper.setProps({page:2});await flushPromises();await surface.trigger('pointerup',{clientX:200,clientY:200});
 expect(wrapper.emitted('create-region')).toBeUndefined();
 await surface.trigger('pointerdown',{clientX:50,clientY:50});await surface.trigger('pointercancel',{clientX:200,clientY:200});
 expect(wrapper.emitted('create-region')).toBeUndefined();wrapper.unmount();
});
it('cannot paint a late cancelled render over a newer page',async()=>{
 const pending=deferred<void>(),cancel=vi.fn();
 const old={getViewport:()=>({width:800,height:300}),render:()=>({promise:pending.promise,cancel})};
 pdf.getDocument.mockReturnValue({promise:Promise.resolve({getPage:(n:number)=>Promise.resolve(n===1?old:page(300,800))}),destroy:()=>Promise.resolve()});
 const wrapper=mount(PdfReviewCanvas,{props:{pdfUrl:'/synthetic.pdf',pageCount:2,regions:[]}});await flushPromises();
 await wrapper.setProps({page:2});await flushPromises();expect(cancel).toHaveBeenCalled();
 pending.resolve();await flushPromises();expect(wrapper.get('canvas').attributes('width')).toBe('300');wrapper.unmount();
});
