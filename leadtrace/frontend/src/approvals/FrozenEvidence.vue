<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from "vue";
import { t } from "../i18n";
import { evidenceUsage, type Row } from "./comparison";
const PdfReviewCanvas = defineAsyncComponent(() => import("../pdf-viewer/PdfReviewCanvas.vue"));
const props = defineProps<{ evidence: Row; snapshot: Record<string, unknown>; paperId: string; currentSourceSha?: string }>();
const expanded = ref(false);
const page = computed(() => Number(props.evidence.page_number));
const pdfUrl = computed(() => `/api/v2/papers/${encodeURIComponent(props.paperId)}/source-pdf`);
const sameSource = computed(() => Boolean(props.evidence.source_sha256) && props.evidence.source_sha256 === (props.snapshot.source as Row | undefined)?.sha256 && props.evidence.source_sha256 === props.currentSourceSha);
const bounds = computed(() => ["x0", "y0", "x1", "y1"].map(key => props.evidence[key] == null ? NaN : Number(props.evidence[key])));
const hasBounds = computed(() => bounds.value.every(value => Number.isFinite(value) && value >= 0 && value <= 1) && bounds.value[2] > bounds.value[0] && bounds.value[3] > bounds.value[1]);
const regions = computed(() => hasBounds.value ? [{id: String(props.evidence.id), pageNumber: page.value, x0: bounds.value[0], y0: bounds.value[1], x1: bounds.value[2], y1: bounds.value[3], rotation: 0}] : []);
const usage = computed(() => evidenceUsage(props.snapshot, props.evidence));
</script>
<template>
  <article class="frozen-evidence" data-frozen-evidence>
    <strong>{{ evidence.caption || evidence.label || evidence.source_context || t("证据") }}</strong>
    <p>{{ t("第 {page} 页", { page }) }} <span v-if="evidence.kind">· {{ evidence.kind }}</span></p>
    <blockquote v-if="evidence.quoted_text">{{ evidence.quoted_text }}</blockquote>
    <p v-if="evidence.source_context">{{ evidence.source_context }}</p>
    <p v-if="evidence.reviewer_note">{{ evidence.reviewer_note }}</p>
    <p v-if="usage.length" class="evidence-usage">{{ t("支持对象") }}: {{ usage.join(" · ") }}</p>
    <p v-if="hasBounds" class="evidence-coordinates">{{ t("原文区域") }}: {{ bounds.map(value => value.toFixed(3)).join(" · ") }}</p>
    <template v-if="sameSource">
      <a data-evidence-pdf-locator :href="`${pdfUrl}#page=${page}`" target="_blank" rel="noopener">{{ t("在 Source PDF 第") }} {{ page }} {{ t("页核对 bbox ↗") }}</a>
      <details v-if="hasBounds" class="evidence-preview" @toggle="expanded = ($event.target as HTMLDetailsElement).open">
        <summary>{{ t("查看原图区域") }}</summary>
        <PdfReviewCanvas v-if="expanded" :pdf-url="pdfUrl" :page-count="Number((snapshot.source as Row | undefined)?.page_count || page)" :page="page" :regions="regions" :read-only="true" :allow-rotation="false" />
      </details>
    </template>
    <p v-else class="message is-error">{{ t("证据来源与冻结 PDF 不一致，请核对原文版本。") }}</p>
  </article>
</template>
<style scoped>
.frozen-evidence { min-width: 0; border-top: 1px solid var(--line); padding: .8rem 0; }
.frozen-evidence p { margin: .4rem 0; overflow-wrap: anywhere; }
.frozen-evidence blockquote { margin: .7rem 0; padding: .5rem .8rem; border-left: 3px solid var(--ink-muted); background: var(--surface); white-space: pre-wrap; }
.evidence-coordinates, .evidence-usage { font-size: .85rem; color: var(--ink-muted); }
.evidence-preview { margin-top: .75rem; }
summary { cursor: pointer; }
</style>
