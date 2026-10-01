<script setup lang="ts">
import { t } from '../../i18n';
import { highlightRole,highlightStatus,type DisplayHighlight } from '../../v2/highlights';
import ReviewHint from './ReviewHint.vue';
withDefaults(defineProps<{
 items:DisplayHighlight[];compounds:{id:string;compound_label:string;display_name?:string|null}[];
 evidence:{id:string;page_number:number;quoted_text?:string|null;caption?:string|null}[];
 depiction?:(compoundId:string)=>string|undefined;editable?:boolean;
}>(),{editable:false});
defineEmits<{edit:[item:DisplayHighlight];remove:[item:DisplayHighlight]}>();
const roles=['study_start','paper_selected'] as const;
</script>
<template><section class="paper-highlights" data-paper-highlights>
  <h2>{{ t('文章级分子标注') }}</h2><p>{{ t('研究起点与论文优选由文章依据决定，独立于 Lineage 的 root / intermediate / terminal。') }}</p>
  <section v-for="role in roles" :key="role"><h3>{{ t(highlightRole(role)) }}</h3>
    <p v-if="!items.some(x=>x.role===role)" class="section-empty">{{ t('尚未记录有来源依据的标注；不代表文章没有此类分子。') }}</p>
    <div class="highlight-card-grid"><article v-for="item in items.filter(x=>x.role===role)" :key="item.id" class="highlight-card" :data-highlight-status="item.review_status">
      <header><strong>Compound {{ compounds.find(x=>x.id===item.compound_id)?.compound_label??'?' }}</strong><span class="status-chip">{{ t(highlightStatus(item.review_status)) }}</span><ReviewHint :hint="item.review_hint" /></header>
      <img v-if="depiction?.(item.compound_id)" :key="depiction(item.compound_id)" :src="depiction(item.compound_id)" :alt="t('化合物与结构')" @error="($event.target as HTMLImageElement).hidden=true">
      <p>{{ compounds.find(x=>x.id===item.compound_id)?.display_name }}</p><p><strong>{{ t('适用范围') }}: </strong>{{ item.scope }}</p><p>{{ item.rationale }}</p>
      <details><summary>{{ t('来源 Evidence') }} · {{ t('PDF 页码') }} {{ evidence.find(x=>x.id===item.evidence_id)?.page_number??'?' }}</summary><template v-for="source in evidence.filter(x=>x.id===item.evidence_id)" :key="source.id"><p>{{ source.caption }}</p><blockquote>{{ source.quoted_text }}</blockquote></template></details>
      <div v-if="editable" class="editor-actions"><button type="button" class="button-secondary" @click="$emit('edit',item)">{{ t('编辑') }}</button><button type="button" class="button-quiet" @click="$emit('remove',item)">{{ t('删除') }}</button></div>
    </article></div>
  </section>
</section></template>
<style scoped>.highlight-card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:12px}.highlight-card{border:1px solid var(--line-strong);border-radius:10px;padding:16px}.highlight-card[data-highlight-status="draft"] .status-chip,.highlight-card[data-highlight-status="unresolved"] .status-chip{background:var(--amber-pale);color:var(--amber-deep)}.highlight-card[data-highlight-status="reviewer_confirmed"] .status-chip{background:var(--teal-pale);color:var(--teal)}.highlight-card header{display:flex;gap:8px;flex-wrap:wrap}.highlight-card img{display:block;width:100%;height:160px;object-fit:contain}.highlight-card blockquote{margin:10px 0;white-space:pre-wrap}.highlight-card p{overflow-wrap:anywhere}</style>
