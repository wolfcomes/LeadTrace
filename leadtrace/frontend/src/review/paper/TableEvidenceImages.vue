<script setup lang="ts">
import {computed,ref,watch} from 'vue';
import {t} from '../../i18n';
import FrozenPdfCrop from '../../approvals/FrozenPdfCrop.vue';
import {validateCrop,useFrozenPdfPool,type CropBounds} from '../../approvals/frozenPdf';
import {useModalFocus} from '../../approvals/useModalFocus';
const props=defineProps<{evidence:Array<Record<string,unknown>>;paperId:string;sourceSha:string;pageCount?:number}>();
useFrozenPdfPool();
const pdfUrl=computed(()=>`/api/v2/papers/${encodeURIComponent(props.paperId)}/source-pdf`);
const images=computed(()=>props.evidence.map(e=>({...e,bounds:validateCrop((e.bbox??e) as Record<string,unknown>)} as Record<string,unknown>&{bounds:CropBounds|null})).filter(e=>e.kind==='table'&&e.source_sha256===props.sourceSha&&Number(e.page_number)>=1&&(!props.pageCount||Number(e.page_number)<=props.pageCount)&&e.bounds));
const opened=ref(new Set<string>());
const selected=ref<string>(),fullPage=ref(false),modal=ref<HTMLElement>();
const current=computed(()=>images.value.find(e=>e.id===selected.value));
const expanded=computed({get:()=>!!current.value,set:value=>{if(!value)selected.value=undefined;}});
useModalFocus(expanded,modal);
watch(()=>[props.paperId,props.evidence],()=>{selected.value=undefined;});
function zoom(id:unknown){selected.value=String(id);fullPage.value=false;}
</script>
<template>
 <div class="table-evidence-images">
  <article v-for="item in images" :key="String(item.id)" data-table-evidence-image>
   <p>p{{item.page_number}} · {{item.caption||t('原文 Table 截图')}}</p>
   <details @toggle="($event.target as HTMLDetailsElement).open?opened.add(String(item.id)):opened.delete(String(item.id))"><summary>{{t('查看 Table 截图')}}</summary><FrozenPdfCrop natural-size v-if="opened.has(String(item.id))" :url="pdfUrl" :sha="sourceSha" :page="Number(item.page_number)" :bounds="item.bounds!" :label="String(item.caption||t('原文 Table 截图'))" /></details>
   <button type="button" class="button-quiet" data-table-evidence-zoom @click="zoom(item.id)">{{t('放大查看')}}</button>
   <a :href="`${pdfUrl}#page=${item.page_number}`" target="_blank" rel="noopener">{{t('打开原文页')}}</a>
  </article>
 </div>
 <Teleport to="body"><div v-if="current" ref="modal" class="table-image-overlay" role="dialog" aria-modal="true" :aria-label="t('原文 Table 截图')" tabindex="-1" @keydown.esc="selected=undefined" @click.self="selected=undefined"><section class="table-image-modal"><header><strong>{{current.caption}} · p{{current.page_number}}</strong><button class="button-secondary" type="button" @click="fullPage=!fullPage">{{t(fullPage?'区域截图':'整页查看')}}</button><button class="button-quiet" type="button" @click="selected=undefined">{{t('关闭')}}</button></header><FrozenPdfCrop :url="pdfUrl" :sha="sourceSha" :page="Number(current.page_number)" :bounds="fullPage?{x0:0,y0:0,x1:1,y1:1}:current.bounds!" eager :label="String(current.caption||t('原文 Table 截图'))" /></section></div></Teleport>
</template>
<style scoped>
.table-evidence-images{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px}.table-evidence-images article{min-width:0;border:1px solid var(--line);border-radius:6px;padding:10px}.table-evidence-images p{overflow-wrap:anywhere}.table-evidence-images a{font-size:.8rem}.table-image-overlay{position:fixed;inset:0;z-index:1000;background:var(--overlay-backdrop);padding:20px;overflow:auto}.table-image-modal{max-width:1100px;margin:auto;background:var(--paper);padding:16px;border-radius:8px}.table-image-modal header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}.table-image-modal strong{flex:1}summary{cursor:pointer;margin-bottom:8px}
</style>
