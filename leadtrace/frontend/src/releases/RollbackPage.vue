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
  <div class="rollback-page admin-page review-workspace">
    <header class="page-heading"><div><p class="eyebrow">CONTROLLED ROLLBACK</p><h1>版本回滚</h1><p>从历史清单创建一个新的发布版本，不删除中间修订和审计记录。</p></div><RouterLink class="button-secondary" to="/admin/releases">返回版本历史</RouterLink></header>
    <p v-if="error" class="message inline-feedback is-error" role="alert">{{ error }}</p>
    <section class="rollback-form panel">
      <label for="rollback-target">目标历史版本</label>
      <select id="rollback-target" v-model="targetId" class="form-control"><option value="">请选择历史版本</option><option v-for="release in historical" :key="release.id" :value="release.id">{{ release.release_key }} · {{ release.title }}</option></select>
      <div v-if="selected" class="target-summary"><strong>{{ selected.title }}</strong><code>{{ selected.id }}</code><p>{{ selected.notes || "无发布说明" }}</p></div>
      <label for="rollback-reason">回滚理由</label>
      <textarea id="rollback-reason" v-model="reason" class="form-control" rows="5" placeholder="说明回滚原因、影响范围和核查依据"></textarea>
      <div class="actions"><RouterLink class="button-secondary" to="/admin/releases">取消</RouterLink><button class="button-danger" type="button" :disabled="busy || !targetId || !reason.trim()" @click="rollback">创建回滚版本</button></div>
    </section>
  </div>
</template>
