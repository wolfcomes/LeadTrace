<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ApiError } from "../api/client";
import { getPublishedPaper, publishedAssetUrl } from "../v2/api";
import type { PublishedPaperDetail } from "../v2/types";

type State = "loading" | "ready" | "not-found" | "error";
const route = useRoute();
const state = ref<State>("loading");
const detail = ref<PublishedPaperDetail | null>(null);
const error = ref<string | null>(null);
const snapshot = computed(() => detail.value?.snapshot ?? null);
const compoundLabels = computed(() => new Map(snapshot.value?.compounds.map((compound) => [compound.id, compound.compound_label]) ?? []));
const evidenceById = computed(() => new Map(snapshot.value?.evidence.map((item) => [item.id, item]) ?? []));

function assetUrl(assetId: string): string {
  return publishedAssetUrl(String(detail.value?.paper_id ?? ""), assetId);
}
function edgeLabel(edgeId: string): string {
  const edge = snapshot.value?.lineage_edges.find((item) => item.id === edgeId);
  return edge
    ? `${compoundLabels.value.get(edge.parent_compound_id) ?? edge.parent_compound_id} → ${compoundLabels.value.get(edge.child_compound_id) ?? edge.child_compound_id}`
    : edgeId;
}
function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value));
}
async function load(): Promise<void> {
  const paperId = String(route.params.paperId ?? "");
  if (!paperId) return;
  state.value = "loading";
  detail.value = null;
  error.value = null;
  try {
    detail.value = await getPublishedPaper(paperId);
    state.value = "ready";
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) state.value = "not-found";
    else {
      state.value = "error";
      error.value = caught instanceof ApiError ? `已批准文章未能读取。请求编号：${caught.requestId ?? "未知"}` : "已批准文章未能读取。";
    }
  }
}
watch(() => route.params.paperId, load, { immediate: true });
</script>

<template>
  <div class="published-page published-paper-detail" data-published-paper-detail>
    <RouterLink class="back-link" :to="{ name: 'papers' }">← 返回已批准文章</RouterLink>
    <section v-if="state === 'loading'" class="page-state" aria-live="polite">正在读取 Published Paper Version…</section>
    <section v-else-if="state === 'not-found'" class="page-state" data-published-not-found><span class="state-symbol" aria-hidden="true">404</span><h1>未找到已批准文章</h1><p>该文章尚未批准，或编号不存在。</p></section>
    <section v-else-if="state === 'error'" class="page-state" role="alert"><span class="state-symbol is-error" aria-hidden="true">!</span><h1>{{ error }}</h1><button class="button-secondary" type="button" @click="load">重新加载</button></section>
    <template v-else-if="detail && snapshot">
      <header class="paper-hero">
        <div class="hero-main">
          <div class="paper-identifiers"><span><code>{{ detail.bibliography.paper_key }}</code></span><span v-if="detail.bibliography.doi">DOI <code>{{ detail.bibliography.doi }}</code></span></div>
          <h1>{{ detail.bibliography.title }}</h1>
          <p>{{ detail.bibliography.journal }} · {{ detail.bibliography.publication_year }} · {{ detail.bibliography.volume }}({{ detail.bibliography.issue }})</p>
        </div>
        <aside class="published-version-card"><span>Published Paper Version</span><strong>版本 {{ detail.version_number }}</strong><small>{{ formatDate(detail.published_at) }}</small><code>{{ detail.content_hash }}</code></aside>
      </header>

      <section class="content-section panel">
        <div class="section-heading"><div><p class="eyebrow">COMPOUNDS & STRUCTURES</p><h2>化合物与结构</h2></div><span>{{ snapshot.compounds.length }} compounds</span></div>
        <div class="published-compound-grid">
          <article v-for="compound in snapshot.compounds" :key="compound.id">
            <header><strong>{{ compound.compound_label }}</strong><span>{{ compound.display_name }}</span></header>
            <div v-for="structure in snapshot.structures.filter((item) => item.compound_id === compound.id)" :key="structure.id">
              <img v-if="structure.depiction_asset_id" data-published-depiction :src="assetUrl(structure.depiction_asset_id)" :alt="`${compound.compound_label} RDKit 结构`">
              <code>{{ structure.canonical_smiles ?? structure.smiles ?? "—" }}</code>
              <span class="status-chip">{{ structure.status }}</span>
            </div>
          </article>
        </div>
      </section>

      <section class="content-section panel">
        <div class="section-heading"><div><p class="eyebrow">LINEAGE</p><h2>Lead optimization Lineage</h2></div><span>{{ snapshot.lineages.length }} lineages</span></div>
        <article v-for="lineage in snapshot.lineages" :key="lineage.id" class="published-lineage-card">
          <header><strong>{{ lineage.lineage_label }}</strong><span>{{ lineage.description }}</span></header>
          <div class="lineage-member-roles">
            <span v-for="member in snapshot.lineage_members.filter((item) => item.lineage_id === lineage.id)" :key="member.id"><strong>{{ compoundLabels.get(member.compound_id) }}</strong><small>{{ member.role }}</small></span>
          </div>
          <div v-for="edge in snapshot.lineage_edges.filter((item) => item.lineage_id === lineage.id)" :key="edge.id" class="published-edge-row">
            <strong>{{ compoundLabels.get(edge.parent_compound_id) }} → {{ compoundLabels.get(edge.child_compound_id) }}</strong>
            <span>{{ edge.relation_type }} · {{ edge.modification_summary ?? "—" }}</span>
          </div>
        </article>
        <p v-if="!snapshot.lineages.length" class="section-empty">该文章没有报告 Lineage。</p>
      </section>

      <section class="content-section panel split-section">
        <div>
          <div class="section-heading"><div><p class="eyebrow">EDGE EVIDENCE</p><h2>关系证据</h2></div></div>
          <article v-for="item in snapshot.evidence" :key="item.id" class="published-evidence-card">
            <header><strong>{{ item.kind }} · 第 {{ item.page_number }} 页</strong><span>{{ item.caption }}</span></header>
            <img v-if="item.crop_asset_id" data-published-evidence-crop :src="assetUrl(item.crop_asset_id)" alt="Edge Evidence crop">
            <blockquote v-if="item.quoted_text">{{ item.quoted_text }}</blockquote>
            <small v-for="link in snapshot.edge_evidence_links.filter((row) => row.evidence_id === item.id)" :key="link.id">{{ link.role }} · {{ edgeLabel(link.edge_id) }}</small>
          </article>
          <p v-if="!snapshot.evidence.length" class="section-empty">该文章没有报告 Evidence。</p>
        </div>
        <div>
          <div class="section-heading"><div><p class="eyebrow">ACTIVITY</p><h2>活性数据</h2></div></div>
          <div class="activity-table-wrap">
            <table v-if="snapshot.activities.length" class="data-table">
              <thead><tr><th>Compound</th><th>Assay</th><th>Metric</th><th>Value</th><th>Evidence</th></tr></thead>
              <tbody><tr v-for="activity in snapshot.activities" :key="activity.id"><td>{{ compoundLabels.get(activity.compound_id) }}</td><td>{{ activity.assay_name }}</td><td>{{ activity.metric }}</td><td><strong>{{ activity.operator }} {{ activity.value }} {{ activity.unit ?? "" }}</strong></td><td>{{ activity.evidence_id ? evidenceById.get(activity.evidence_id)?.caption ?? "已关联" : "—" }}</td></tr></tbody>
            </table>
            <p v-else class="section-empty">该文章没有报告 Activity。</p>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
