import {mount} from '@vue/test-utils';
import {expect,it,vi} from 'vitest';
import TableEvidenceImages from '../src/review/paper/TableEvidenceImages.vue';
const sha='c'.repeat(64);
const base={id:'first',kind:'table',source_sha256:sha,page_number:1,bbox:{x0:.1,y0:.2,x1:.9,y1:.8},caption:'Synthetic table'};
it('renders only linked valid regions, supports multiple pages and opens crops on demand',async()=>{
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
 const w=mount(TableEvidenceImages,{props:{paperId:'paper',sourceSha:sha,pageCount:3,evidence:[base,{...base,id:'second',page_number:2},{...base,id:'bad-source',source_sha256:'b'.repeat(64)},{...base,id:'bad-page',page_number:5},{...base,id:'bad-box',bbox:{x0:.9,y0:.2,x1:.1,y1:.8}}]},global:{stubs:{FrozenPdfCrop:{props:['page','bounds','sha'],template:'<div data-synthetic-crop>{{page}}</div>'}}}});
 expect(w.findAll('[data-table-evidence-image]')).toHaveLength(2);expect(w.findAll('[data-synthetic-crop]')).toHaveLength(0);expect(fetcher).not.toHaveBeenCalled();
 const details=w.findAll('details')[1]!;(details.element as HTMLDetailsElement).open=true;await details.trigger('toggle');expect(w.get('[data-synthetic-crop]').text()).toBe('2');
 await w.get('[data-table-evidence-zoom]').trigger('click');expect(document.querySelector('[role="dialog"]')).not.toBeNull();
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));await w.vm.$nextTick();expect(document.querySelector('[role="dialog"]')).toBeNull();
 expect(w.findAll('a')[1]!.attributes('href')).toBe('/api/v2/papers/paper/source-pdf#page=2');w.unmount();vi.unstubAllGlobals();
});
