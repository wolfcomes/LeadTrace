import { computed, inject, onBeforeUnmount, provide, ref, watchEffect, type InjectionKey } from 'vue';

function createPendingEdits() {
  const pending = ref(new Set<symbol>());
  return {
    blocked: computed(() => pending.value.size > 0),
    set(key:symbol, value:boolean) { if(value) pending.value.add(key); else pending.value.delete(key); },
  };
}
const key:InjectionKey<ReturnType<typeof createPendingEdits>> = Symbol('pendingWorkspaceEdits');
export function providePendingEdits() { const value=createPendingEdits();provide(key,value);return value; }
/** Register editable local state or an in-flight save; normal viewing stays unblocked. */
export function usePendingEdit(pending:()=>unknown) {
  const state=inject(key,undefined);if(!state)return;
  const token=Symbol('editor');
  watchEffect(()=>state.set(token,Boolean(pending())),{flush:'sync'});
  onBeforeUnmount(()=>state.set(token,false));
}
