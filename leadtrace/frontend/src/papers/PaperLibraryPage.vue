<script setup lang="ts">
import { t, locale } from "../i18n";
import { onMounted, ref } from "vue";
import { ApiError } from "../api/client";
import { listPublishedPapers } from "../v2/api";
import type { PublishedPaperList } from "../v2/types";

const papers = ref<PublishedPaperList["items"]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const errorRequestId = ref<string>();

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeZone: "Asia/Shanghai" }).format(new Date(value));
}
async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    papers.value = (await listPublishedPapers()).items;
  } catch (caught) {
    errorRequestId.value = caught instanceof ApiError ? caught.requestId : undefined;
    error.value = caught instanceof ApiError ? "已批准文章未能读取。" : "已批准文章未能读取。";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div class="published-page library-page">
    <header class="page-heading page-heading--editorial">
      <div><p class="eyebrow">PUBLISHED PAPER VERSIONS</p><h1>{{ t("已批准文章") }}</h1><p>{{ t("这里只展示经 Admin 批准的不可变文章版本，不读取 Reviewer 的可编辑 Workspace。") }}</p></div>
      <span v-if="!loading" class="status-chip">{{ papers.length }} {{ t("篇") }}</span>
    </header>
    <p v-if="error" class="message inline-feedback is-error" role="alert">{{ t(error) }} <small v-if="errorRequestId">{{ t("请求编号：{requestId}", { requestId: errorRequestId }) }}</small></p>
    <section v-if="loading" class="page-state" aria-live="polite">{{ t("正在读取已批准文章…") }}</section>
    <section v-else-if="papers.length" class="published-paper-list panel" :aria-label="t('已批准文章')">
      <article v-for="paper in papers" :key="paper.paper_id" class="published-paper-row" data-published-paper-row>
        <div>
          <div class="paper-identifiers"><span><code>{{ paper.paper_key }}</code></span><span v-if="paper.doi">DOI <code>{{ paper.doi }}</code></span></div>
          <h2>{{ paper.title }}</h2>
          <p>{{ paper.journal }} · {{ paper.publication_year }} · {{ paper.volume }}({{ paper.issue }})</p>
        </div>
        <div class="published-version-meta"><strong>{{ t("版本") }} {{ paper.version_number }}</strong><span>{{ formatDate(paper.published_at) }}</span><code>{{ paper.content_hash.slice(0, 12) }}…</code></div>
        <RouterLink class="button-secondary" data-open-published-paper :to="{ name: 'paper-detail', params: { paperId: paper.paper_id } }">{{ t("查看 →") }}</RouterLink>
      </article>
    </section>
    <section v-else-if="!error" class="page-state" data-empty-state><span class="state-symbol" aria-hidden="true">0</span><h2>{{ t("暂无已批准文章") }}</h2><p>{{ t("Reviewer Submission 经 Admin 批准后会出现在这里。") }}</p></section>
  </div>
</template>
