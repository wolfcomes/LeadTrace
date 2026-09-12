<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { createReleaseOperationKey, fetchReleases, rollbackToRelease, type AdminRelease } from "./api";

const router = useRouter();
const releases = ref<AdminRelease[]>([]);
const targetId = ref("");
const reason = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const operationKey = ref(createReleaseOperationKey("rollback"));
const historical = computed(() => releases.value.filter((entry) => !entry.is_current && entry.manifest_finalized));
const selected = computed(() => historical.value.find((entry) => entry.id === targetId.value) ?? null);

function requestReference(caught: ApiError): string {
  return caught.requestId ? ` 请求编号：${caught.requestId}` : "";
}

onMounted(async () => {
  try {
    releases.value = await fetchReleases();
  } catch {
    error.value = "历史版本未能读取。";
  }
});

async function rollback(): Promise<void> {
  if (!targetId.value || !reason.value.trim()) return;
  busy.value = true;
  error.value = null;
  try {
    await rollbackToRelease(targetId.value, reason.value.trim(), operationKey.value);
    operationKey.value = createReleaseOperationKey("rollback");
    await router.push("/admin/releases");
  } catch (caught) {
    if (caught instanceof ApiError && caught.kind === "conflict") {
      error.value = `当前发布版本已经变化，请重新选择回滚目标。${requestReference(caught)}`;
    } else if (caught instanceof ApiError && caught.kind === "validation") {
      error.value = `回滚目标未通过完整性校验，当前版本保持不变。${requestReference(caught)}`;
    } else {
      error.value = `回滚未能完成。当前版本保持不变。${
        caught instanceof ApiError ? requestReference(caught) : ""
      }`;
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="rollback-page">
    <header class="page-heading"><div><p class="eyebrow">CONTROLLED ROLLBACK</p><h1>版本回滚</h1><p>从历史清单创建一个新的发布版本，不删除中间修订和审计记录。</p></div><RouterLink class="button-secondary" to="/admin/releases">返回版本历史</RouterLink></header>
    <p v-if="error" class="message" role="alert">{{ error }}</p>
    <section class="rollback-form">
      <label for="rollback-target">目标历史版本</label>
      <select id="rollback-target" v-model="targetId"><option value="">请选择历史版本</option><option v-for="release in historical" :key="release.id" :value="release.id">{{ release.release_key }} · {{ release.title }}</option></select>
      <div v-if="selected" class="target-summary"><strong>{{ selected.title }}</strong><code>{{ selected.id }}</code><p>{{ selected.notes || "无发布说明" }}</p></div>
      <label for="rollback-reason">回滚理由</label>
      <textarea id="rollback-reason" v-model="reason" rows="5" placeholder="说明回滚原因、影响范围和核查依据"></textarea>
      <div class="actions"><RouterLink class="button-secondary" to="/admin/releases">取消</RouterLink><button class="button-danger" type="button" :disabled="busy || !targetId || !reason.trim()" @click="rollback">创建回滚版本</button></div>
    </section>
  </div>
</template>

<style scoped>
.rollback-page{max-width:920px;padding:clamp(24px,4vw,52px)}.page-heading a,.actions a{text-decoration:none}.message{padding:11px 14px;border-left:3px solid var(--danger);color:var(--danger);background:#fff;font-size:.76rem}.rollback-form{display:grid;gap:10px;padding:22px;border:1px solid var(--line);background:#fff}.rollback-form label{margin-top:6px;color:var(--ink-700);font-size:.72rem;font-weight:720}.rollback-form select,.rollback-form textarea{width:100%;padding:10px;border:1px solid var(--line);border-radius:6px;background:#fff;font:inherit}.target-summary{padding:14px;border-left:3px solid var(--gold-600);background:var(--canvas)}.target-summary strong,.target-summary code{display:block}.target-summary code{margin-top:6px;color:var(--ink-500);font-size:.62rem}.target-summary p{margin:8px 0 0;color:var(--ink-600);font-size:.74rem}.actions{display:flex;justify-content:flex-end;gap:10px;margin-top:12px}.button-danger{min-height:40px;padding:8px 14px;border:1px solid #a94d48;border-radius:6px;color:#fff;background:#9e3f3a;cursor:pointer}.button-danger:disabled{opacity:.5;cursor:not-allowed}
</style>
