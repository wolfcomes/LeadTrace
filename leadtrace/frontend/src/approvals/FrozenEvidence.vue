<script setup lang="ts">
import { computed, ref } from "vue";
import { t } from "../i18n";
import { evidenceUsage, type Row } from "./comparison";
import { validateCrop, useFrozenPdfPool } from "./frozenPdf";
import { useModalFocus } from "./useModalFocus";
import FrozenPdfCrop from "./FrozenPdfCrop.vue";
const props = defineProps<{
  evidence: Row;
  snapshot: Record<string, unknown>;
  paperId: string;
  currentSourceSha?: string;
  changeLabel?: string;
}>();
useFrozenPdfPool();
const expanded = ref(false),
  fullPage = ref(false);
const page = computed(() => Number(props.evidence.page_number));
const pdfUrl = computed(
  () => `/api/v2/papers/${encodeURIComponent(props.paperId)}/source-pdf`,
);
const sameSource = computed(
  () =>
    Boolean(props.evidence.source_sha256) &&
    props.evidence.source_sha256 ===
      (props.snapshot.source as Row | undefined)?.sha256 &&
    props.evidence.source_sha256 === props.currentSourceSha,
);
const bounds = computed(() => validateCrop(props.evidence));
const usage = computed(() => evidenceUsage(props.snapshot, props.evidence));
const heading = computed(() =>
  String(
    props.evidence.caption ||
      props.evidence.label ||
      props.evidence.source_context ||
      t("证据"),
  ),
);
const modal = ref<HTMLElement>();
useModalFocus(expanded, modal);
</script>
<template>
  <article
    class="frozen-evidence"
    data-frozen-evidence
    :data-evidence-id="String(evidence.id)"
  >
    <header>
      <strong>{{ heading }}</strong
      ><span v-if="changeLabel" class="status-chip">{{ t(changeLabel) }}</span>
    </header>
    <p class="evidence-caption">
      {{ t("第 {page} 页", { page }) }}
      <span v-if="evidence.kind">· {{ evidence.kind }}</span>
    </p>
    <template v-if="sameSource">
      <FrozenPdfCrop
        v-if="bounds"
        :url="pdfUrl"
        :sha="String(evidence.source_sha256)"
        :page="page"
        :bounds="bounds"
        :label="heading"
      />
      <p v-else class="section-empty">
        {{ t("未提供区域截图；请结合文字证据核对原文。") }}
      </p>
      <div class="evidence-actions">
        <button
          v-if="bounds"
          type="button"
          class="button-quiet"
          data-enlarge-evidence
          @click="
            expanded = true;
            fullPage = false;
          "
        >
          {{ t("放大查看") }}</button
        ><button
          v-if="bounds"
          type="button"
          class="button-quiet"
          data-open-evidence-page
          @click="
            expanded = true;
            fullPage = true;
          "
        >
          {{ t("打开整页并标出区域") }}</button
        ><a
          v-else
          data-evidence-pdf-locator
          :href="`${pdfUrl}#page=${page}`"
          target="_blank"
          rel="noopener"
          >{{ t("打开 Source PDF ↗") }}</a
        >
      </div>
    </template>
    <p v-else class="message is-error">
      {{ t("证据来源与冻结 PDF 不一致，请核对原文版本。") }}
    </p>
    <blockquote v-if="evidence.quoted_text">
      {{ evidence.quoted_text }}
    </blockquote>
    <p v-if="evidence.source_context && evidence.source_context !== heading">
      {{ evidence.source_context }}
    </p>
    <p v-if="evidence.reviewer_note">{{ evidence.reviewer_note }}</p>
    <p v-if="usage.length" class="evidence-usage">
      {{ t("支持对象") }}: {{ usage.join(" · ") }}
    </p>
    <details v-if="bounds && sameSource" class="evidence-coordinates">
      <summary>{{ t("原文区域") }}</summary>
      {{
        Object.values(bounds)
          .map((x) => x.toFixed(3))
          .join(" · ")
      }}
    </details>
    <Teleport to="body"
      ><div
        v-if="expanded && bounds && sameSource"
        ref="modal"
        tabindex="-1"
        class="evidence-lightbox"
        role="dialog"
        aria-modal="true"
        :aria-label="heading"
        @click.self="expanded = false"
      >
        <section>
          <header>
            <strong>{{ heading }} · {{ t("第 {page} 页", { page }) }}</strong
            ><button
              type="button"
              class="button-secondary"
              autofocus
              @click="expanded = false"
            >
              {{ t("关闭") }}
            </button>
          </header>
          <div class="evidence-expanded-image">
            <FrozenPdfCrop
              :url="pdfUrl"
              :sha="String(evidence.source_sha256)"
              :page="page"
              :bounds="fullPage ? { x0: 0, y0: 0, x1: 1, y1: 1 } : bounds"
              :label="heading"
              eager
            />
            <div
              v-if="fullPage"
              class="evidence-region-marker"
              :style="{
                left: `${bounds.x0 * 100}%`,
                top: `${bounds.y0 * 100}%`,
                width: `${(bounds.x1 - bounds.x0) * 100}%`,
                height: `${(bounds.y1 - bounds.y0) * 100}%`,
              }"
            />
          </div>
        </section></div
    ></Teleport>
  </article>
</template>
<style scoped>
.frozen-evidence {
  min-width: 0;
  padding: 0.8rem 0;
}
.frozen-evidence header {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
}
.frozen-evidence p {
  margin: 0.4rem 0;
  overflow-wrap: anywhere;
}
.frozen-evidence blockquote {
  margin: 0.65rem 0;
  padding: 0.5rem 0.8rem;
  border-left: 3px solid var(--ink-muted);
  background: var(--surface);
  white-space: pre-wrap;
  font-size: 0.9rem;
}
.evidence-caption,
.evidence-coordinates,
.evidence-usage {
  font-size: 0.8rem;
  color: var(--ink-muted);
}
.evidence-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.4rem 0;
}
summary {
  cursor: pointer;
}
.evidence-lightbox {
  position: fixed;
  inset: 0;
  z-index: 1500;
  background: color-mix(in srgb, var(--ink) 80%, transparent);
  overflow: auto;
  padding: 2rem;
}
.evidence-lightbox > section {
  background: var(--paper, white);
  padding: 1rem;
  border-radius: 10px;
  max-width: 1100px;
  margin: auto;
}
.evidence-lightbox header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  margin-bottom: 1rem;
}
.evidence-expanded-image {
  position: relative;
}
.evidence-region-marker {
  position: absolute;
  border: 3px solid var(--teal-deep);
  background: color-mix(in srgb, var(--teal) 8%, transparent);
  pointer-events: none;
  box-sizing: border-box;
}
</style>
