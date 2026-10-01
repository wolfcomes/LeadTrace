<script setup lang="ts">
import { t } from "../../i18n";
import { computed, ref } from 'vue';
import PdfReviewCanvas from '../../pdf-viewer/PdfReviewCanvas.vue';
import type { Evidence, PaperWorkspace } from '../../v2/types';
const props = defineProps<{ evidence: Evidence; workspace: PaperWorkspace; contentVersion?: number }>();
const showRegion = ref(false);
const pdfUrl = computed(() => `/api/v2/papers/${props.workspace.bibliography.paper_id}/source-pdf`);
const regions = computed(() => props.evidence.bbox ? [{ id: props.evidence.id, regionKey: props.evidence.caption || t('证据区域'), pageNumber: props.evidence.page_number, ...props.evidence.bbox, rotation: 0 }] : []);
</script>
<template>
  <div class="evidence-excerpt" data-evidence-excerpt :data-evidence-id="evidence.id">
    <header><span class="status-chip">{{ evidence.kind }}</span><a data-evidence-pdf-locator :href="`${pdfUrl}#page=${evidence.page_number}`" target="_blank" rel="noopener">{{ t("原文第 {page} 页 ↗", { page: evidence.page_number }) }}</a></header>
    <details class="record-detail"><summary>{{ t('查看证据内容') }}</summary>
    <blockquote v-if="evidence.quoted_text">{{ evidence.quoted_text }}</blockquote>
    <p v-if="evidence.caption">{{ evidence.caption }}</p>
    <small v-if="evidence.reviewer_note">{{ t("核对备注：") }}{{ evidence.reviewer_note }}</small>
    <template v-if="evidence.bbox">
      <button class="button-quiet" data-show-evidence-region type="button" @click.stop="showRegion = !showRegion">{{ showRegion ? t("收起原图区域") : t("查看原图区域") }}</button>
      <PdfReviewCanvas v-if="showRegion" :pdf-url="pdfUrl" :page-count="workspace.source.page_count" :page="evidence.page_number" :regions="regions" :selected-region-id="evidence.id" :read-only="true" :allow-rotation="false" />
    </template>
    </details>
  </div>
</template>
