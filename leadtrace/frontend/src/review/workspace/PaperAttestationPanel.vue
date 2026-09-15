<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { Workspace } from "./types";

const ATTESTATION_STATEMENT = "我确认已核查该 Paper 冻结范围内的全部必需对象、来源和结构证据，且不存在未解决 blocker。";

const props = withDefaults(defineProps<{
  workspace: Workspace;
  editable: boolean;
  busy?: boolean;
}>(), { busy: false });

const emit = defineEmits<{
  attest: [payload: {
    expected_version: number;
    scope_hash: string;
    statement: string;
    confirmed: true;
  }];
}>();

const confirmed = ref(false);
watch(() => props.workspace.attestation, () => { confirmed.value = false; });

const currentAttestation = computed<NonNullable<Workspace["attestation"]> | null>(() => {
  const value = props.workspace.attestation;
  if (!value) return null;
  return value;
});
const attestationCurrent = computed(() => Boolean(
  currentAttestation.value
  && !currentAttestation.value.stale
  && currentAttestation.value.changeset_version === props.workspace.changeset.version
  && currentAttestation.value.scope_hash === props.workspace.scope.scope_hash,
));
const complete = computed(() => (
  props.workspace.progress.blocker_count === 0
  && props.workspace.progress.resolved_count === props.workspace.progress.scope_count
  && props.workspace.progress.scope_count === props.workspace.scope.item_count
));
const canAttest = computed(() => Boolean(
  props.editable
  && !props.busy
  && complete.value
  && confirmed.value
  && !attestationCurrent.value,
));

function attest(): void {
  if (!canAttest.value) return;
  emit("attest", {
    expected_version: props.workspace.changeset.version,
    scope_hash: props.workspace.scope.scope_hash,
    statement: ATTESTATION_STATEMENT,
    confirmed: true,
  });
}
</script>

<template>
  <section class="paper-attestation panel" data-paper-attestation aria-labelledby="paper-attestation-title">
    <header class="section-heading">
      <div>
        <p class="eyebrow">PAPER ATTESTATION</p>
        <h2 id="paper-attestation-title">Reviewer 核查确认</h2>
      </div>
      <span v-if="attestationCurrent" class="status-chip is-ok" data-attestation-current>已确认</span>
      <span v-else-if="currentAttestation" class="status-chip is-pending" data-attestation-stale>上次确认已过期</span>
    </header>

    <dl class="attestation-progress">
      <div><dt>必需范围</dt><dd>{{ workspace.progress.resolved_count }} / {{ workspace.progress.scope_count }}</dd></div>
      <div><dt>blocker</dt><dd>{{ workspace.progress.blocker_count }}</dd></div>
      <div><dt>冻结范围对象</dt><dd>{{ workspace.scope.item_count }}</dd></div>
      <div><dt>草稿版本</dt><dd>v{{ workspace.changeset.version }}</dd></div>
    </dl>

    <p v-if="!complete" class="attestation-blocker" data-attestation-blocker>
      仍有未解决对象或 blocker；完成全部范围后才能进行 Paper 级确认。
    </p>
    <div v-else class="attestation-ready" data-attestation-ready>
      <p>所有必需对象已处理。确认以下固定声明后，Reviewer attestation 会绑定到当前版本和范围哈希。</p>
      <label class="attestation-confirmation">
        <input v-model="confirmed" type="checkbox" data-attestation-confirm :disabled="!editable || busy || attestationCurrent">
        我已阅读并确认固定声明
      </label>
      <blockquote data-attestation-statement>{{ ATTESTATION_STATEMENT }}</blockquote>
      <code class="scope-hash" data-scope-hash>scope hash · {{ workspace.scope.scope_hash }}</code>
      <button class="button-primary" data-attest-paper type="button" :disabled="!canAttest" @click="attest">
        {{ attestationCurrent ? "当前版本已确认" : busy ? "正在记录确认…" : "确认 Paper 核查" }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.paper-attestation { display: grid; gap: 14px; padding: 18px; background: var(--paper-deep); }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.section-heading h2 { margin: 0; }
.attestation-progress { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0; border: 1px solid var(--line); background: var(--line); }
.attestation-progress div { display: grid; gap: 5px; padding: 10px; background: var(--surface); }
.attestation-progress dt { color: var(--ink-muted); font-size: .63rem; }
.attestation-progress dd { margin: 0; font: 700 .9rem/1.1 var(--font-mono); }
.attestation-blocker { margin: 0; padding: 10px 12px; border-left: 3px solid var(--coral); color: var(--coral-deep); background: color-mix(in srgb, var(--coral) 10%, white); font-size: .72rem; }
.attestation-ready { display: grid; gap: 10px; }
.attestation-ready p { margin: 0; color: var(--ink-soft); font-size: .72rem; }
.attestation-confirmation { display: flex; align-items: center; gap: 8px; color: var(--ink-soft); font-size: .75rem; }
blockquote { margin: 0; padding: 11px 13px; border-left: 3px solid var(--teal); color: var(--ink); background: var(--surface); font-size: .76rem; line-height: 1.6; }
.scope-hash { overflow-wrap: anywhere; color: var(--ink-muted); font-size: .61rem; }
@media (max-width: 760px) { .attestation-progress { grid-template-columns: 1fr 1fr; } }
</style>
