<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  RouterLink,
  useRoute,
  useRouter,
  type LocationQueryRaw,
} from "vue-router";

import { ApiError } from "../../api/client";
import { fetchMoleculeObjectQueue } from "../api";
import type {
  MoleculeObjectQueue,
  MoleculeObjectQueueItem,
  MoleculeObjectType,
  QueueState,
} from "../workspace/types";

type ViewState = "loading" | "ready" | "error";

const route = useRoute();
const router = useRouter();
const state = ref<ViewState>("loading");
const payload = ref<MoleculeObjectQueue>();
const requestId = ref<string>();
let loadGeneration = 0;

const statusLabels: Record<QueueState, string> = {
  localization_or_split: "需定位或拆分",
  needs_ocsr: "待 OCSR",
  proposal_review: "待审核",
  source_or_attachment: "缺少来源",
  structure_assembly: "待结构组装",
  complete: "已处理",
};

const objectTypeLabels: Record<MoleculeObjectType, string> = {
  complete_molecule: "完整分子",
  shared_scaffold: "共享骨架",
  r_group: "R 基",
  linker: "连接子",
  variable_site: "可变位点",
  replacement_fragment: "替换片段",
  multi_structure_region: "多结构区域",
  reaction_or_scheme_context: "反应/方案上下文",
  mixed_chemical_region: "混合化学区域",
  non_structure: "非结构内容",
  uncertain: "待确认",
};

const queueStates = Object.keys(statusLabels) as QueueState[];
const objectTypes = Object.keys(objectTypeLabels) as MoleculeObjectType[];

function queryString(name: string): string | undefined {
  const value = route.query[name];
  return typeof value === "string" ? value : undefined;
}

const selectedStatus = computed(() => queryString("status") as QueueState | undefined);
const selectedObjectType = computed(
  () => queryString("object_type") as MoleculeObjectType | undefined,
);
const selectedBlocker = computed(() => queryString("has_blocker"));
const activeItems = computed(() => (
  payload.value?.items.filter((item) => item.state !== "complete") ?? []
));
const completedItems = computed(() => (
  payload.value?.items.filter((item) => item.state === "complete") ?? []
));

function linkFor(item: MoleculeObjectQueueItem) {
  const query = {
    view: item.deep_link.view,
    page: String(item.deep_link.page),
    object: item.deep_link.object,
    ...(item.deep_link.proposal ? { proposal: item.deep_link.proposal } : {}),
  };
  return item.changeset_id
    ? { path: `/review/changesets/${item.changeset_id}`, query }
    : { path: "/review/changesets", query: { task: item.review_task_id, ...query } };
}

function progressLabel(item: MoleculeObjectQueueItem): string {
  return `${item.paper_progress.resolved_count} / ${item.paper_progress.scope_count}`;
}

async function load(): Promise<void> {
  const generation = ++loadGeneration;
  state.value = "loading";
  requestId.value = undefined;
  try {
    const result = await fetchMoleculeObjectQueue({
      status: selectedStatus.value,
      object_type: selectedObjectType.value,
      has_blocker: selectedBlocker.value === undefined
        ? undefined
        : selectedBlocker.value === "true",
      page: 1,
      limit: 50,
    });
    if (generation !== loadGeneration) return;
    payload.value = result;
    state.value = "ready";
  } catch (error) {
    if (generation !== loadGeneration) return;
    state.value = "error";
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
  }
}

function updateFilter(name: string, event: Event): void {
  const value = (event.target as HTMLSelectElement).value;
  const query: LocationQueryRaw = { ...route.query, tab: "molecules" };
  if (value) query[name] = value;
  else delete query[name];
  void router.replace({ path: route.path, query });
}

watch(
  () => [route.query.status, route.query.object_type, route.query.has_blocker],
  () => { void load(); },
);
onMounted(load);
</script>

<template>
  <section class="molecule-object-queue panel" data-molecule-queue aria-labelledby="molecule-queue-title">
    <header class="panel-heading molecule-queue-heading">
      <div>
        <p class="eyebrow">FIRST-PAGE MOLECULE OBJECTS</p>
        <h2 id="molecule-queue-title">首页分子对象专项核查</h2>
        <p>集中处理定位、OCSR proposal、来源附件和 Structure 组装，不产生对象级“已核验”状态。</p>
      </div>
      <div v-if="payload" class="molecule-queue-counts" data-queue-counts aria-label="对象状态统计">
        <span>待审核 {{ payload.status_counts.proposal_review }}</span>
        <span>需定位 {{ payload.status_counts.localization_or_split }}</span>
        <span>待结构 {{ payload.status_counts.structure_assembly }}</span>
        <span>已处理 {{ payload.status_counts.complete }}</span>
      </div>
    </header>

    <form class="filter-toolbar molecule-queue-filters" aria-label="分子对象筛选" @submit.prevent>
      <label class="form-field">
        核查状态
        <select
          name="queue-status"
          class="form-control"
          :value="selectedStatus ?? ''"
          @change="updateFilter('status', $event)"
        >
          <option value="">全部状态</option>
          <option v-for="queueState in queueStates" :key="queueState" :value="queueState">
            {{ statusLabels[queueState] }}
          </option>
        </select>
      </label>
      <label class="form-field">
        对象类型
        <select
          name="queue-object-type"
          class="form-control"
          :value="selectedObjectType ?? ''"
          @change="updateFilter('object_type', $event)"
        >
          <option value="">全部类型</option>
          <option v-for="objectType in objectTypes" :key="objectType" :value="objectType">
            {{ objectTypeLabels[objectType] }}
          </option>
        </select>
      </label>
      <label class="form-field">
        阻塞情况
        <select
          name="queue-blocker"
          class="form-control"
          :value="selectedBlocker ?? ''"
          @change="updateFilter('has_blocker', $event)"
        >
          <option value="">全部对象</option>
          <option value="true">仅看阻塞项</option>
          <option value="false">仅看已处理项</option>
        </select>
      </label>
    </form>

    <div v-if="state === 'loading'" class="review-state page-state compact-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>正在读取分子对象队列…</p>
    </div>
    <div v-else-if="state === 'error'" class="review-state page-state compact-state is-error" role="alert">
      <span class="state-symbol" aria-hidden="true">!</span>
      <h3>暂时无法读取对象队列</h3>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </div>
    <div v-else-if="!payload?.items.length" class="review-state page-state compact-state" data-empty-state>
      <span class="state-symbol" aria-hidden="true">—</span>
      <h3>当前筛选下没有对象</h3>
      <p>调整状态或对象类型后重试。</p>
    </div>

    <template v-else>
      <div v-if="activeItems.length" class="table-wrap molecule-queue-table-wrap">
        <table class="data-table molecule-queue-table">
          <thead>
            <tr>
              <th scope="col">裁剪图</th>
              <th scope="col">Paper / 对象</th>
              <th scope="col">当前状态</th>
              <th scope="col">Paper 进度</th>
              <th scope="col"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in activeItems" :key="item.visual_object.id" data-molecule-row>
              <td>
                <img
                  v-if="item.crop_asset"
                  class="molecule-crop-thumbnail"
                  :src="item.crop_asset.url"
                  :alt="`${item.paper_key} 的分子对象裁剪图`"
                >
                <span v-else class="crop-placeholder" role="img" :aria-label="`${item.paper_key} 暂无裁剪图`">无裁剪图</span>
              </td>
              <th scope="row">
                <strong>{{ item.paper_key }}</strong>
                <code>{{ item.visual_object.object_key }}</code>
                <small>第 {{ item.page }} 页 · {{ objectTypeLabels[item.visual_object.object_type] }}</small>
              </th>
              <td>
                <span class="status-chip" :data-queue-state="item.state">
                  {{ item.blocking ? "阻塞 · " : "" }}{{ statusLabels[item.state] }}
                </span>
                <small v-if="item.reasons.length" class="queue-reason">{{ item.reasons.join(" · ") }}</small>
              </td>
              <td>
                <strong class="progress-ratio">{{ progressLabel(item) }}</strong>
                <small>{{ item.paper_progress.blocker_count }} 个阻塞项</small>
              </td>
              <td>
                <RouterLink class="button-primary compact-action" :to="linkFor(item)">
                  {{ item.changeset_id ? "继续核查" : "开始核查" }}
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <details v-if="completedItems.length" class="completed-object-group" data-completed-group>
        <summary>已处理对象 · {{ completedItems.length }}</summary>
        <div class="table-wrap">
          <table class="data-table molecule-queue-table">
            <tbody>
              <tr v-for="item in completedItems" :key="item.visual_object.id">
                <th scope="row">
                  <strong>{{ item.paper_key }}</strong>
                  <code>{{ item.visual_object.object_key }}</code>
                </th>
                <td><span class="status-chip is-complete">✓ {{ statusLabels[item.state] }}</span></td>
                <td>{{ progressLabel(item) }}</td>
                <td><RouterLink class="button-secondary compact-action" :to="linkFor(item)">查看</RouterLink></td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </template>
  </section>
</template>
