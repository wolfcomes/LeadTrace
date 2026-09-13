<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";

import { ApiError } from "../api/client";
import {
  fetchAdminPapers,
  type AdminPaperList,
  type AdminPaperWorkflow,
} from "./api";


type ViewState = "loading" | "ready" | "error";

const route = useRoute();
const router = useRouter();
const state = ref<ViewState>("loading");
const payload = ref<AdminPaperList | null>(null);
const requestId = ref<string>();
const search = ref("");
const doi = ref("");
const workflowState = ref("");
const publicationStatus = ref("");
let loadSequence = 0;

const workflowStates: ReadonlyArray<{ value: AdminPaperWorkflow; label: string; short: string }> = [
  { value: "initial", label: "初始状态", short: "初始" },
  { value: "ai_baseline_unassigned", label: "AI 提取基线（未分配）", short: "未分配" },
  { value: "ai_baseline_in_review", label: "AI 提取基线（已分配，人工核验进行中）", short: "核验中" },
  { value: "human_review_pending_approval", label: "人工核验结束（待批）", short: "待审批" },
  { value: "admin_approved", label: "Admin 已批准", short: "已批准" },
];

const statusLabel = computed(() => new Map(
  workflowStates.map((entry) => [entry.value, entry.label]),
));

function queryValue(name: string): string {
  const value = route.query[name];
  return typeof value === "string" ? value : "";
}

function pageFromRoute(): number {
  const value = Number.parseInt(queryValue("page"), 10);
  return Number.isInteger(value) && value > 0 ? value : 1;
}

function restoreFilters(): void {
  search.value = queryValue("search");
  doi.value = queryValue("doi");
  workflowState.value = queryValue("workflow_state");
  publicationStatus.value = queryValue("publication_status");
}

function requestParams(): Record<string, string> {
  const params: Record<string, string> = {
    page: String(pageFromRoute()),
    page_size: "20",
  };
  for (const key of [
    "candidate_id",
    "search",
    "doi",
    "workflow_state",
    "publication_status",
    "assignee_id",
  ]) {
    const value = queryValue(key);
    if (value) params[key] = value;
  }
  return params;
}

async function load(): Promise<void> {
  const sequence = ++loadSequence;
  restoreFilters();
  state.value = "loading";
  requestId.value = undefined;
  try {
    const response = await fetchAdminPapers(requestParams());
    if (sequence !== loadSequence) return;
    payload.value = response;
    state.value = "ready";
  } catch (error) {
    if (sequence !== loadSequence) return;
    payload.value = null;
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    state.value = "error";
  }
}

function filterQuery(page = 1): LocationQueryRaw {
  const query: LocationQueryRaw = { page: String(page) };
  const candidateId = queryValue("candidate_id");
  if (candidateId) query.candidate_id = candidateId;
  const values = {
    search: search.value.trim(),
    doi: doi.value.trim(),
    workflow_state: workflowState.value,
    publication_status: publicationStatus.value,
  };
  for (const [key, value] of Object.entries(values)) {
    if (value) query[key] = value;
  }
  return query;
}

async function applyFilters(): Promise<void> {
  await router.replace({ name: "admin-papers", query: filterQuery(1) });
}

async function resetFilters(): Promise<void> {
  search.value = "";
  doi.value = "";
  workflowState.value = "";
  publicationStatus.value = "";
  await router.replace({ name: "admin-papers", query: filterQuery(1) });
}

async function goToPage(page: number): Promise<void> {
  await router.replace({ name: "admin-papers", query: { ...route.query, page: String(page) } });
}

watch(() => route.fullPath, load, { immediate: true });
</script>

<template>
  <div class="catalog-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">ADMIN PAPER CATALOG</p>
        <h1>文章目录</h1>
        <p>查看数据库中的全部文章、AI 提取质量、分配进度和人工核验状态。</p>
      </div>
      <div v-if="payload" class="source-summary">
        <span>{{ payload.source.title }}</span>
        <strong :data-verification="payload.source.verification_status">
          {{ payload.source.verification_status === "human_verified" ? "已人工核验" : "未验证" }}
        </strong>
        <small>{{ payload.source.publication_status === "published" ? "已发布" : "未发布" }}</small>
      </div>
    </header>

    <section v-if="payload" class="status-overview" aria-label="文章流程状态统计">
      <button
        v-for="entry in workflowStates"
        :key="entry.value"
        type="button"
        :class="{ active: workflowState === entry.value }"
        :data-workflow-count="entry.value"
        @click="workflowState = workflowState === entry.value ? '' : entry.value; applyFilters()"
      >
        <span>{{ entry.short }}</span>
        <strong>{{ (payload.status_counts[entry.value] ?? 0).toLocaleString("zh-CN") }}</strong>
        <small>{{ entry.label }}</small>
      </button>
    </section>

    <form class="filter-panel" data-admin-paper-filters @submit.prevent="applyFilters">
      <label class="wide">搜索文章<input v-model="search" type="search" placeholder="标题、DOI、文章编号或靶点"></label>
      <label>DOI<input v-model="doi" type="text" placeholder="10.xxxx/…"></label>
      <label>流程状态<select id="admin-paper-workflow" v-model="workflowState">
        <option value="">全部状态</option>
        <option v-for="entry in workflowStates" :key="entry.value" :value="entry.value">{{ entry.label }}</option>
      </select></label>
      <label>发布状态<select v-model="publicationStatus">
        <option value="">全部</option>
        <option value="unpublished">未发布</option>
        <option value="published">已发布</option>
      </select></label>
      <div class="filter-actions">
        <button class="button-primary" type="submit">应用筛选</button>
        <button class="button-secondary" type="button" @click="resetFilters">清除</button>
      </div>
    </form>

    <section v-if="state === 'loading'" class="page-state" aria-live="polite">
      <span class="spinner" aria-hidden="true"></span><p>正在读取数据库文章…</p>
    </section>
    <section v-else-if="state === 'error'" class="page-state error" role="alert">
      <span>!</span><h2>暂时无法读取文章目录</h2>
      <p>请稍后重试；如问题持续，请将请求编号提供给管理员。</p>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <template v-else-if="payload">
      <div class="result-heading">
        <strong>共 {{ payload.pagination.total_items.toLocaleString("zh-CN") }} 篇</strong>
        <span v-if="payload.pagination.total_pages">第 {{ payload.pagination.page }} / {{ payload.pagination.total_pages }} 页</span>
      </div>
      <div v-if="payload.items.length" class="table-wrap">
        <table>
          <thead><tr><th>文章</th><th>流程状态</th><th>数据库内容</th><th>分配</th><th>可见性</th><th><span class="sr-only">操作</span></th></tr></thead>
          <tbody>
            <tr v-for="paper in payload.items" :key="paper.id" data-admin-paper>
              <th scope="row">
                <code>{{ paper.paper_key }}</code>
                <RouterLink :to="{ name: 'admin-paper-detail', params: { paperId: paper.id }, query: route.query.candidate_id ? { candidate_id: route.query.candidate_id } : {} }">{{ paper.title }}</RouterLink>
                <small>{{ paper.doi || "无 DOI" }} · {{ paper.year || "年份未知" }}<template v-if="paper.target"> · {{ paper.target }}</template></small>
              </th>
              <td><span class="workflow-badge" :data-state="paper.workflow_state">{{ statusLabel.get(paper.workflow_state) }}</span></td>
              <td class="quality-cell">
                <span>{{ paper.quality.compounds }} 分子</span>
                <span>{{ paper.quality.confirmed_structures }}/{{ paper.quality.structures }} 结构确认</span>
                <span>{{ paper.quality.evidence }} 证据</span>
              </td>
              <td>
                <template v-if="paper.task"><strong class="assignee">{{ paper.task.assignee_display_name }}</strong><small>{{ paper.task.status }}</small></template>
                <span v-else class="muted">未分配</span>
              </td>
              <td><span class="visibility" :data-status="paper.publication_status">{{ paper.publication_status === "published" ? "已发布" : "未发布" }}</span><small v-if="paper.verification_status !== 'human_verified'" class="unverified">未验证</small></td>
              <td class="actions"><RouterLink class="detail-link" :to="{ name: 'admin-paper-detail', params: { paperId: paper.id }, query: route.query.candidate_id ? { candidate_id: route.query.candidate_id } : {} }">查看 / 修改 →</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
      <section v-else class="page-state compact"><span>0</span><h2>没有符合条件的文章</h2><p>请调整搜索词或筛选条件。</p></section>
      <nav v-if="payload.pagination.total_pages > 0" class="pagination" aria-label="文章目录分页">
        <button type="button" :disabled="payload.pagination.page <= 1" @click="goToPage(payload.pagination.page - 1)">上一页</button>
        <span>第 {{ payload.pagination.page }} / {{ payload.pagination.total_pages }} 页</span>
        <button type="button" :disabled="payload.pagination.page >= payload.pagination.total_pages" @click="goToPage(payload.pagination.page + 1)">下一页</button>
      </nav>
    </template>
  </div>
</template>

<style scoped>
.catalog-page{max-width:1580px;margin:auto;padding:clamp(26px,4vw,52px)}
.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:30px;margin-bottom:24px}.page-heading h1{margin:0;color:var(--ink-950);font:600 clamp(2rem,3vw,3rem)/1.12 Georgia,"Noto Serif SC Variable",serif}.page-heading p:last-child{max-width:720px;margin:12px 0 0;color:var(--ink-650);line-height:1.7}
.source-summary{display:grid;min-width:210px;gap:6px;padding:14px 16px;border:1px solid var(--line);border-left:3px solid var(--forest-750);background:#fff}.source-summary span{font-size:.75rem;font-weight:750}.source-summary strong,.source-summary small{width:max-content;padding:3px 7px;border-radius:99px;font-size:.65rem}.source-summary strong{color:#8b3d2f;background:#fbe9e3}.source-summary strong[data-verification="human_verified"]{color:#1f674c;background:#e4f3eb}.source-summary small{color:var(--ink-650);background:#eef2ef}
.status-overview{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;margin:24px 0;background:var(--line);border:1px solid var(--line)}.status-overview button{display:grid;min-height:112px;align-content:start;gap:4px;padding:15px;border:0;background:#fff;text-align:left;cursor:pointer}.status-overview button:hover,.status-overview button.active{background:var(--forest-100)}.status-overview span{color:var(--ink-500);font-size:.65rem;font-weight:760;letter-spacing:.08em}.status-overview strong{color:var(--forest-900);font:600 1.9rem/1.1 Georgia,serif}.status-overview small{color:var(--ink-650);font-size:.67rem;line-height:1.4}
.filter-panel{display:grid;grid-template-columns:minmax(240px,1.5fr) minmax(150px,.7fr) minmax(220px,1fr) minmax(130px,.6fr) auto;gap:12px;align-items:end;padding:16px;border:1px solid var(--line);background:#fff}.filter-panel label{display:grid;gap:6px;color:var(--ink-650);font-size:.67rem;font-weight:750}.filter-panel input,.filter-panel select{min-height:40px;padding:8px 10px;border:1px solid var(--line-strong);border-radius:6px;background:#fff;color:var(--ink-800)}.filter-actions{display:flex;gap:8px}.button-secondary{min-height:40px;padding:8px 13px;border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--ink-650);cursor:pointer}
.result-heading{display:flex;justify-content:space-between;margin:24px 0 10px;color:var(--ink-650);font-size:.75rem}.result-heading strong{color:var(--ink-950)}.table-wrap{overflow:auto;border-top:2px solid var(--forest-900);background:#fff;box-shadow:var(--shadow-sm)}table{width:100%;min-width:1120px;border-collapse:collapse}th,td{padding:15px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}thead th{color:var(--ink-500);background:#f7f9f7;font-size:.65rem;letter-spacing:.08em}tbody th{max-width:360px}tbody th code,tbody th a,tbody th small{display:block}tbody th code{margin-bottom:4px;color:var(--gold-700);font-size:.62rem}tbody th a{overflow:hidden;color:var(--ink-950);font-size:.78rem;font-weight:720;text-decoration:none;text-overflow:ellipsis;white-space:nowrap}tbody th small,.assignee+small{margin-top:5px;color:var(--ink-500);font-size:.65rem}.workflow-badge,.visibility,.unverified{display:inline-flex;width:max-content;padding:4px 7px;border-radius:99px;font-size:.64rem;font-weight:700}.workflow-badge{max-width:210px;color:#285944;background:#e7f1ec;line-height:1.4}.workflow-badge[data-state="human_review_pending_approval"]{color:#37617a;background:#e8f1f6}.workflow-badge[data-state="admin_approved"]{color:#1f674c;background:#dff2e8}.workflow-badge[data-state="initial"]{color:var(--ink-650);background:#eef1ef}.quality-cell span{display:block;color:var(--ink-650);font-size:.66rem;line-height:1.7}.assignee{display:block;color:var(--ink-800);font-size:.7rem}.muted{color:var(--ink-500);font-size:.68rem}.visibility{color:#1f674c;background:#e4f3eb}.visibility[data-status="unpublished"]{color:#725d2b;background:#f7efd9}.unverified{margin-top:5px;color:#8b3d2f;background:#fbe9e3}.detail-link{color:var(--forest-750);font-size:.7rem;font-weight:750;text-decoration:none;white-space:nowrap}
.pagination{display:flex;justify-content:flex-end;align-items:center;gap:12px;margin-top:18px;color:var(--ink-650);font-size:.7rem}.pagination button{padding:7px 11px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}.pagination button:disabled{cursor:not-allowed;opacity:.45}.page-state{display:flex;min-height:260px;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--ink-650);text-align:center}.page-state h2,.page-state p{margin:0}.page-state h2{color:var(--ink-950);font:600 1.3rem/1.2 Georgia,serif}.page-state p{font-size:.75rem}.page-state>span{display:grid;width:44px;height:44px;place-items:center;border:1px solid var(--line);border-radius:50%}.spinner{border-top-color:var(--forest-750)!important;animation:spin .8s linear infinite}.compact{min-height:180px}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1100px){.status-overview{grid-template-columns:repeat(2,1fr)}.filter-panel{grid-template-columns:1fr 1fr}.filter-actions{grid-column:1/-1}}
@media(max-width:720px){.page-heading{flex-direction:column}.source-summary{width:100%}.status-overview,.filter-panel{grid-template-columns:1fr}.filter-actions{grid-column:auto}}
@media(prefers-reduced-motion:reduce){.spinner{animation:none}}
</style>
