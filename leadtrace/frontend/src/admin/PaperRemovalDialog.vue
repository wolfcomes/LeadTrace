<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { z } from 'zod';
import { t } from '../i18n';
import { ApiError, apiRequest } from '../api/client';
import { useAuthStore } from '../auth/store';
import { fetchPaperManagement, type PaperManagement } from './aiTasks';
const props = defineProps<{paper: {id: string; paper_key: string; title: string}}>();
const emit = defineEmits<{close: []; removed: []}>();
const auth = useAuthStore();
const management = ref<PaperManagement>();
const reason = ref('');
const confirmation = ref('');
const busy = ref(false);
const loading = ref(true);
const error = ref('');
const requestId = ref<string>();
const dialog = ref<HTMLElement>();
let previousFocus: HTMLElement | null = null;
let disposed = false;
const canRemove = computed(() => !!management.value && !loading.value && !busy.value && !!reason.value.trim() && confirmation.value === props.paper.paper_key);
async function refresh() {
  loading.value = true; management.value = undefined; confirmation.value = ''; error.value = ''; requestId.value = undefined;
  try { const value = await fetchPaperManagement(props.paper.id); if (!disposed) management.value = value; }
  catch (e) { if (!disposed) { error.value = '无法读取文章当前状态，请刷新后重试。'; requestId.value = e instanceof ApiError ? e.requestId : undefined; } }
  finally { loading.value = false; }
}
async function submit() {
  if (!canRemove.value || !management.value) return;
  busy.value = true; error.value = ''; requestId.value = undefined;
  const current = management.value;
  try {
    await apiRequest(`/api/v2/admin/papers/${encodeURIComponent(props.paper.id)}`, z.object({paper_id:z.string(),removed_at:z.string(),audit_event_id:z.string()}), {method:'DELETE',csrfToken:auth.csrfToken,body:{reason:reason.value.trim(),confirm_paper_key:confirmation.value,expected_workspace_id:current.workspace_id,expected_workspace_version:current.workspace_version,expected_task_version:current.task_version}});
    emit('removed');
  } catch (e) {
    requestId.value = e instanceof ApiError ? e.requestId : undefined;
    error.value = e instanceof ApiError && e.code === 'PAPER_TASK_ACTIVE' ? '该文章仍有 AI 任务，请先等待完成或取消任务，再刷新状态。' : e instanceof ApiError && e.code === 'PAPER_VERSION_CONFLICT' ? '文章状态已发生变化，请刷新状态并重新确认。' : e instanceof ApiError && e.status === 404 ? '文章已被移除或不存在，请关闭并刷新目录。' : '移除失败，请刷新状态后重试。';
    management.value = undefined; confirmation.value = '';
  } finally { busy.value = false; }
}
function close() { if (!busy.value) emit('close'); }
function keydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.preventDefault(); close(); }
  if (e.key !== 'Tab' || !dialog.value) return;
  const nodes = Array.from(dialog.value.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),textarea:not([disabled])'));
  const first = nodes[0], last = nodes.at(-1);
  if (!first) { e.preventDefault(); dialog.value.focus(); }
  else if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { e.preventDefault(); last?.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
onMounted(async()=>{previousFocus=document.activeElement instanceof HTMLElement?document.activeElement:null;await nextTick();dialog.value?.focus();await refresh();});
onBeforeUnmount(()=>{disposed=true;previousFocus?.focus();});
</script>
<template>
  <div class="removal-backdrop" @click.self="close">
    <section ref="dialog" class="removal-dialog panel" role="dialog" aria-modal="true" aria-labelledby="removal-title" tabindex="-1" data-removal-dialog @keydown="keydown">
      <h2 id="removal-title">{{ t('从主站移除文章') }}</h2>
      <p><code>{{ paper.paper_key }}</code><br><strong>{{ paper.title }}</strong></p>
      <p>{{ t('文章将从目录、审批、任务及已发布内容中隐藏，原始 PDF 保留在服务器。历史记录保留，可由维护人员恢复。') }}</p>
      <form @submit.prevent="submit">
        <label class="form-field">{{ t('移除原因') }}<textarea v-model="reason" name="reason" required maxlength="2000" rows="3" :disabled="busy" /></label>
        <label class="form-field">{{ t('输入文章编号以确认') }}<input v-model="confirmation" name="confirm_paper_key" autocomplete="off" :disabled="busy || loading || !management" :placeholder="paper.paper_key" /></label>
        <p v-if="loading" aria-live="polite">{{ t('正在读取…') }}</p>
        <p v-if="error" role="alert" class="inline-feedback is-error">{{ t(error) }} <small v-if="requestId">{{ requestId }}</small></p>
        <footer>
          <button type="button" class="button-secondary" :disabled="busy" @click="close">{{ t('取消') }}</button>
          <button v-if="!management && !loading" type="button" class="button-secondary" data-refresh-removal :disabled="busy" @click="refresh">{{ t('刷新状态') }}</button>
          <button type="submit" class="button-secondary removal-confirm" data-confirm-removal :disabled="!canRemove">{{ t(busy ? '正在移除…' : '确认移除（保留 PDF）') }}</button>
        </footer>
      </form>
    </section>
  </div>
</template>
<style scoped>
.removal-backdrop{position:fixed;inset:0;z-index:1000;background:#10233488;display:flex;align-items:center;justify-content:center;padding:20px}.removal-dialog{width:min(580px,100%);max-height:90vh;overflow:auto;padding:24px}.removal-dialog p{overflow-wrap:anywhere}.removal-dialog form{display:grid;gap:16px}.removal-dialog footer{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap}.removal-confirm{color:#a12626;border-color:#a12626}.form-field{display:grid;gap:8px}
</style>
