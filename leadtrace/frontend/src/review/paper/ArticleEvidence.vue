<script setup lang="ts">
import { ref } from 'vue';
import { t } from '../../i18n';
import FrozenPdfCrop from '../../approvals/FrozenPdfCrop.vue';
import { useFrozenPdfPool } from '../../approvals/frozenPdf';
import type { ArticleEvidence, ArticleSourceContext } from './articleMetadata';
const props=defineProps<{evidence?:ArticleEvidence[];sourceContext?:ArticleSourceContext}>();
useFrozenPdfPool();
const opened=ref<number|null>(null);
const labels={main_pdf:'主文',supplement:'补充材料',external:'外部数据库／来源'};
function safeUrl(value?:string|null) {try {const url=new URL(value??'');return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}}
function pdfUrl(entry:ArticleEvidence) {return entry.source_kind==='main_pdf'&&props.sourceContext&&entry.page_number&&entry.page_number<=props.sourceContext.pageCount&&(!entry.source_sha256||entry.source_sha256===props.sourceContext.sha256)?`/api/v2/papers/${encodeURIComponent(props.sourceContext.paperId)}/source-pdf`:null;}
</script>
<template><div data-article-evidence><p v-if="!evidence?.length" class="missing-quote">{{t('尚未补充原文摘录')}}</p><article v-for="(entry,index) in evidence" :key="index" class="quote-entry"><strong>{{t('原文摘录')}}</strong><blockquote>{{entry.quoted_text}}</blockquote><p class="quote-locator">{{t(labels[entry.source_kind])}}<span v-if="entry.page_number"> · PDF p. {{entry.page_number}}</span><span v-if="entry.locator"> · {{entry.locator}}</span></p><a v-if="pdfUrl(entry)" :href="`${pdfUrl(entry)}#page=${entry.page_number}`" target="_blank" rel="noopener" data-article-source-link>{{t('打开对应原文')}} ↗</a><a v-else-if="safeUrl(entry.source_url)" :href="safeUrl(entry.source_url)!" target="_blank" rel="noopener">{{t('打开来源')}} ↗</a><template v-if="entry.bbox && entry.source_sha256===sourceContext?.sha256 && pdfUrl(entry)"><button type="button" class="button-quiet" data-article-crop @click="opened=opened===index?null:index">{{t(opened===index?'收起原图区域':'查看原图区域')}}</button><FrozenPdfCrop v-if="opened===index" :url="pdfUrl(entry)!" :sha="entry.source_sha256!" :page="entry.page_number!" :bounds="{x0:entry.bbox.x,y0:entry.bbox.y,x1:entry.bbox.x+entry.bbox.width,y1:entry.bbox.y+entry.bbox.height}" :label="t('证据区域')" /></template></article></div></template>
<style scoped>.quote-entry{margin:.65rem 0}.quote-entry blockquote{margin:.4rem 0;padding:.5rem .7rem;border-left:3px solid var(--line);white-space:pre-wrap;color:var(--ink);line-height:1.6}.quote-locator,.missing-quote{font-size:.82rem;color:var(--ink-muted)}.quote-entry button{display:block;margin-top:.4rem}</style>
