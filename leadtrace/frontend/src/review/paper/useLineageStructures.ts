import { onBeforeUnmount, ref, watch, type Ref } from 'vue';
import { getCompoundStructure } from '../../v2/api';
import type { Structure } from '../../v2/types';

export type LineageStructureState = { status: 'loading' | 'ready' | 'error'; structure?: Structure | null };

/** Cache only within this workspace; cap concurrent reads and ignore retired requests. */
export function useLineageStructures(workspaceId: () => string, compoundIds: Ref<string[]>) {
  const records = ref<Record<string, LineageStructureState>>({});
  let queue: string[] = [];
  let active = 0;
  let epoch = 0;
  let disposed = false;
  function drain(): void {
    while (!disposed && active < 4 && queue.length) {
      const id = queue.shift()!;
      const requestEpoch = epoch;
      active++;
      void getCompoundStructure(id).then(result => {
        if (!disposed && epoch === requestEpoch) records.value[id] = { status: 'ready', structure: result.structure };
      }).catch(() => {
        if (!disposed && epoch === requestEpoch) records.value[id] = { status: 'error' };
      }).finally(() => {
        if (epoch === requestEpoch) { active--; drain(); }
      });
    }
  }
  function load(ids: string[]): void {
    for (const id of ids) {
      if (records.value[id]) continue;
      records.value[id] = { status: 'loading' };
      queue.push(id);
    }
    // A quick Lineage switch should not wait behind the old graph's queue.
    const visible = new Set(ids);
    queue = [...queue.filter(id => visible.has(id)), ...queue.filter(id => !visible.has(id))];
    drain();
  }
  watch(workspaceId, () => {
    epoch++; active = 0; queue = []; records.value = {};
    load(compoundIds.value);
  });
  watch(compoundIds, load, { immediate: true });
  function retry(id: string): void {
    if (records.value[id]?.status !== 'error') return;
    delete records.value[id]; load([id]);
  }
  onBeforeUnmount(() => { disposed = true; epoch++; queue = []; });
  return { records, retry };
}
