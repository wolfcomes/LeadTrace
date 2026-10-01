import { computed, inject, provide, ref, watch, type InjectionKey } from 'vue';
import { useAuthStore } from '../../auth/store';
import { getReviewProgress, recordView, type ReviewProgress, type ViewItem } from '../../v2/workbench';
import type { PaperWorkspace } from '../../v2/types';
function createProgress(workspace: () => PaperWorkspace | undefined, editable: () => boolean) {
  const auth = useAuthStore();
  const progress = ref<ReviewProgress>();
  const error = ref('');
  const busy = ref(false);
  let generation = 0;
  let queue = Promise.resolve();
  async function refresh() {
    const ws = workspace(); if (!ws) return;
    const epoch = ++generation;
    try {
      const result = await getReviewProgress(ws.id);
      if (epoch === generation && workspace()?.id === ws.id) { progress.value = result; error.value = ''; }
    } catch { if (epoch === generation) error.value = '已读记录读取失败，请重试。'; }
  }
  const find = (kind:string,id:string) => progress.value?.items.find(x => x.kind === kind && x.entity_id === id);
  function view(kind:ViewItem['kind'], id:string, viewed = true, contentVersion?: number): Promise<void> {
    const ws = workspace(), item = find(kind,id);
    if (!ws || !editable() || (viewed && typeof document !== 'undefined' && document.visibilityState !== 'visible')) return Promise.resolve();
    if (!item || progress.value?.workspace_version !== ws.version || (contentVersion !== undefined && contentVersion !== ws.version)) {
      error.value = '内容已更新，请刷新已读记录并重新打开条目。'; return Promise.resolve();
    }
    if (item.viewed === viewed) return Promise.resolve();
    const captured = { ...item };
    queue = queue.then(async () => {
      if (workspace()?.id !== ws.id) return;
      busy.value = true;
      try {
        const result = await recordView(ws.id,captured,viewed,auth.csrfToken);
        if (workspace()?.id === ws.id && (progress.value?.workspace_version ?? 0) <= result.workspace_version) progress.value = result;
        error.value = '';
      } catch { error.value = '已读状态未保存，请刷新后重新打开条目。'; }
      finally { busy.value = false; }
    });
    return queue;
  }
  watch(() => [workspace()?.id,workspace()?.version], () => { void refresh(); }, { immediate:true });
  return { progress, error, busy, refresh, find, view, unread: computed(() => progress.value?.items.filter(x => !x.viewed) ?? []) };
}
type Progress = ReturnType<typeof createProgress>;
const key: InjectionKey<Progress> = Symbol('workspaceReviewProgress');
export function provideReviewProgress(workspace: () => PaperWorkspace | undefined, editable: () => boolean) { const value = createProgress(workspace,editable); provide(key,value); return value; }
export function useReviewProgress() { return inject(key,undefined); }
