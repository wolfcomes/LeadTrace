<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { MoleculeProposalUpdate, StructureValidationResult } from "../api";
import type { WorkspaceMoleculeProposal, WorkspaceStructure } from "./types";

const props = defineProps<{
  proposal: WorkspaceMoleculeProposal;
  structures: WorkspaceStructure[];
  editable: boolean;
  busy?: boolean;
  validation: StructureValidationResult | null;
}>();

const emit = defineEmits<{
  validate: [payload: { smiles: string; selected_component_smiles: string | null; source_comparison: "match" | "mismatch" | "not_compared"; source_verified: boolean }];
  decision: [payload: Omit<MoleculeProposalUpdate, "changeset_id" | "expected_version">];
  "locate-source": [regionId: string];
}>();

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function bool(value: unknown): boolean {
  return value === true;
}

const reviewedSmiles = ref("");
const selectedComponentSmiles = ref("");
const compoundId = ref("");
const resultingStructureId = ref("");
const rationale = ref("");
const sourceComparison = ref<"match" | "mismatch" | "not_compared">("not_compared");
const sourceVerified = ref(false);

function reset(): void {
  const normalized = props.proposal.machine.normalized_values;
  const raw = props.proposal.machine.raw_values;
  reviewedSmiles.value = text(
    props.proposal.review.reviewed_smiles
      ?? normalized.canonical_smiles
      ?? normalized.machine_canonical_smiles
      ?? raw.raw_smiles,
  );
  selectedComponentSmiles.value = text(props.proposal.review.selected_component_smiles);
  compoundId.value = text(props.proposal.review.compound_id);
  resultingStructureId.value = text(props.proposal.review.resulting_structure_id);
  rationale.value = text(props.proposal.review.rationale);
  const comparison = props.proposal.review.source_comparison;
  sourceComparison.value = comparison === "match" || comparison === "mismatch" ? comparison : "not_compared";
  sourceVerified.value = bool(props.proposal.review.source_verified);
}

watch(() => props.proposal, reset, { deep: true, immediate: true });

const rawValues = computed(() => props.proposal.machine.raw_values);
const normalizedValues = computed(() => props.proposal.machine.normalized_values);
const rawSmiles = computed(() => text(rawValues.value.raw_smiles));
const machineCanonicalSmiles = computed(() => text(normalizedValues.value.machine_canonical_smiles ?? normalizedValues.value.canonical_smiles));
const inferenceError = computed(() => text(rawValues.value.inference_error ?? normalizedValues.value.inference_error));
const modelVersion = computed(() => text(rawValues.value.model_version ?? normalizedValues.value.model_version));
const rdkitStatus = computed(() => text(normalizedValues.value.rdkit_status));
const proposalQuality = computed(() => text(normalizedValues.value.proposal_quality));

const tokenConfidences = computed(() => {
  const values = rawValues.value.token_confidences;
  if (!Array.isArray(values)) return [];
  return values.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const token = text((value as Record<string, unknown>).token);
    const confidence = Number((value as Record<string, unknown>).confidence);
    return token && Number.isFinite(confidence) ? [{ token, confidence }] : [];
  });
});
const lowConfidenceTokens = computed(() => tokenConfidences.value.filter((item) => item.confidence < 0.5));

function percent(value: unknown): string {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${Math.round(numeric * 100)}%` : "—";
}

const referenceReady = computed(() => Boolean(compoundId.value.trim() || resultingStructureId.value));
const componentReady = computed(() => (props.validation?.componentCount ?? 0) <= 1 || Boolean(selectedComponentSmiles.value.trim()));
const structureDecisionReady = computed(() => Boolean(
  props.editable
  && !props.busy
  && props.validation?.parseable
  && reviewedSmiles.value.trim()
  && referenceReady.value
  && componentReady.value,
));
const rationaleReady = computed(() => Boolean(props.editable && !props.busy && rationale.value.trim()));

function validationPayload() {
  return {
    smiles: reviewedSmiles.value.trim(),
    selected_component_smiles: selectedComponentSmiles.value.trim() || null,
    source_comparison: sourceComparison.value,
    source_verified: sourceVerified.value,
  };
}

function validate(): void {
  if (!props.editable || props.busy || !reviewedSmiles.value.trim()) return;
  emit("validate", validationPayload());
}

function decide(disposition: "accepted" | "corrected" | "rejected" | "not_applicable"): void {
  if ((disposition === "accepted" || disposition === "corrected") && !structureDecisionReady.value) return;
  if ((disposition === "rejected" || disposition === "not_applicable") && !rationaleReady.value) return;
  emit("decision", {
    disposition,
    reviewed_smiles: disposition === "accepted" || disposition === "corrected" ? reviewedSmiles.value.trim() : null,
    selected_component_smiles: selectedComponentSmiles.value.trim() || null,
    compound_id: compoundId.value.trim() || null,
    resulting_structure_id: resultingStructureId.value || null,
    rationale: rationale.value.trim() || null,
    source_comparison: sourceComparison.value,
    source_verified: sourceVerified.value,
  });
}
</script>

<template>
  <section class="molecule-proposal-inspector" data-proposal-inspector aria-label="OCSR proposal 专用编辑器">
    <header class="typed-inspector-heading">
      <div><p class="eyebrow">OCSR PROPOSAL</p><h2>{{ proposal.proposal_key }}</h2></div>
      <span class="status-chip" :data-state="proposal.disposition">{{ proposal.disposition }}</span>
    </header>

    <section class="machine-evidence" data-machine-evidence aria-label="只读机器证据">
      <h3>只读机器输出</h3>
      <dl>
        <div><dt>raw SMILES</dt><dd><code>{{ rawSmiles || "—" }}</code></dd></div>
        <div><dt>machine canonical</dt><dd><code>{{ machineCanonicalSmiles || "—" }}</code></dd></div>
        <div><dt>mean / min confidence</dt><dd>{{ percent(normalizedValues.mean_token_confidence) }} / {{ percent(normalizedValues.min_token_confidence) }}</dd></div>
        <div><dt>model</dt><dd>{{ modelVersion || proposal.model_run_key }}</dd></div>
        <div><dt>RDKit / quality</dt><dd>{{ rdkitStatus || "—" }} / {{ proposalQuality || "—" }}</dd></div>
        <div v-if="inferenceError"><dt>inference error</dt><dd>{{ inferenceError }}</dd></div>
      </dl>
      <div v-if="lowConfidenceTokens.length" class="low-confidence-tokens">
        <span v-for="token in lowConfidenceTokens" :key="`${token.token}-${token.confidence}`" data-low-confidence-token>{{ token.token }} · {{ percent(token.confidence) }}</span>
      </div>
    </section>

    <button v-if="proposal.source_region_id" class="button-quiet" type="button" @click="emit('locate-source', proposal.source_region_id)">定位到来源 Region</button>

    <label class="form-field">Reviewed SMILES
      <textarea v-model="reviewedSmiles" class="form-control" name="reviewed-smiles" rows="3" :disabled="!editable || busy" @blur="validate"></textarea>
    </label>
    <button class="button-secondary" data-validate-proposal type="button" :disabled="!editable || busy || !reviewedSmiles.trim()" @click="validate">用 RDKit 校验</button>

    <label v-if="(validation?.componentCount ?? 0) > 1" class="form-field">明确选择组分
      <input v-model="selectedComponentSmiles" class="form-control" name="selected-component-smiles" :disabled="!editable || busy" @blur="validate">
    </label>
    <div v-if="validation" class="proposal-validation" :class="validation.parseable ? 'is-ok' : 'is-error'" data-proposal-validation>
      <strong>{{ validation.parseable ? "RDKit 可解析" : "RDKit 不可解析" }}</strong>
      <code v-if="validation.canonicalIsomericSmiles">{{ validation.canonicalIsomericSmiles }}</code>
      <span v-if="validation.messages.length">{{ validation.messages.join(" · ") }}</span>
    </div>

    <label class="form-field">Compound ID
      <input v-model="compoundId" class="form-control" name="compound-id" :disabled="!editable || busy">
    </label>
    <label class="form-field">Resulting Structure
      <select v-model="resultingStructureId" class="form-control" name="resulting-structure" :disabled="!editable || busy">
        <option value="">未选择</option>
        <option v-for="structure in structures" :key="structure.id" :value="structure.id">{{ structure.structure_key }} · {{ structure.state ?? "未定" }}</option>
      </select>
    </label>
    <label class="form-field">来源对照
      <select v-model="sourceComparison" class="form-control" name="proposal-source-comparison" :disabled="!editable || busy">
        <option value="not_compared">尚未对照</option><option value="match">一致</option><option value="mismatch">不一致</option>
      </select>
    </label>
    <label class="check-field"><input v-model="sourceVerified" name="proposal-source-verified" type="checkbox" :disabled="!editable || busy"> 已核对来源</label>
    <label class="form-field">处置理由
      <textarea v-model="rationale" class="form-control" name="rationale" rows="2" :disabled="!editable || busy"></textarea>
    </label>

    <div class="proposal-actions">
      <button class="button-primary" data-accept-proposal type="button" :disabled="!structureDecisionReady" @click="decide('accepted')">接受候选</button>
      <button class="button-secondary" data-correct-proposal type="button" :disabled="!structureDecisionReady" @click="decide('corrected')">保存修正</button>
      <button class="button-quiet" data-reject-proposal type="button" :disabled="!rationaleReady" @click="decide('rejected')">拒绝</button>
      <button class="button-quiet" data-not-applicable-proposal type="button" :disabled="!rationaleReady" @click="decide('not_applicable')">不适用</button>
    </div>
  </section>
</template>

<style scoped>
.molecule-proposal-inspector { display: grid; gap: 13px; }
.typed-inspector-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 9px; }
.typed-inspector-heading h2 { margin: 0; }
.machine-evidence { padding: 12px; border: 1px solid var(--line); background: var(--paper); }
.machine-evidence h3 { margin: 0 0 9px; font-size: .8rem; }
.machine-evidence dl { display: grid; gap: 6px; margin: 0; }
.machine-evidence dl div { display: grid; grid-template-columns: 100px minmax(0, 1fr); gap: 7px; }
.machine-evidence dt { color: var(--ink-muted); font-size: .64rem; }
.machine-evidence dd { min-width: 0; margin: 0; overflow-wrap: anywhere; font-size: .68rem; }
.low-confidence-tokens { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.low-confidence-tokens span { padding: 3px 6px; color: var(--coral-deep); background: color-mix(in srgb, var(--coral) 12%, white); font: .63rem/1.3 var(--font-mono); }
.proposal-validation { display: grid; gap: 4px; padding: 9px; border-left: 3px solid var(--teal); background: var(--teal-pale); font-size: .68rem; }
.proposal-validation.is-error { border-color: var(--coral); background: color-mix(in srgb, var(--coral) 10%, white); }
.proposal-validation code { overflow-wrap: anywhere; }
.check-field { color: var(--ink-soft); font-size: .73rem; }
.proposal-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
</style>
