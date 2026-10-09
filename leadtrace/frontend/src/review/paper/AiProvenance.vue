<script setup lang="ts">
import { computed } from 'vue';
import { locale, t, formatDate } from '../../i18n';
import type { AiProvenanceRecord } from '../../v2/provenance';
const props = defineProps<{ records: AiProvenanceRecord[]; workspaceVersion?: number; compact?: boolean }>();
const unknown = () => t("未记录");
const latestApplied = computed(() => props.records.filter(r => r.applied_workspace_version != null && r.stage !== 'independent_review' && r.outcome !== 'failed')
  .reduce<AiProvenanceRecord | undefined>((last, r) => !last || r.applied_workspace_version! >= last.applied_workspace_version! ? r : last, undefined));
const stages = { prefill: ['预填','Prefill'], producer_self_check: ['生产者自检','Producer self-check'], repair: ['修补','Repair'], independent_review: ['独立复核','Independent review'] };
const verifications = { unknown: ['来源未核实','Unverified provenance'], candidate_declared: ['候选自述','Candidate declaration'], requested_only: ['仅请求配置','Requested configuration only'], request_observed: ['已核对请求记录','Request metadata checked'], mismatch: ['请求配置不一致','Configuration mismatch'] };
const outcomes = { completed: ['流程完成','Run completed'], needs_revision: ['需修订','Needs revision'], partial: ['部分完成','Partial'], failed: ['运行失败','Run failed'], unknown: ['结果未记录','Outcome not recorded'] };
const label = (values: string[]) => values[locale.value === 'en' ? 1 : 0];
</script>
<template>
  <div v-if="compact" class="ai-provenance-compact">
    <span v-if="latestApplied">AI · {{ latestApplied.observed_model ?? latestApplied.model ?? unknown() }} · {{ t("推理强度") }}: {{ latestApplied.observed_reasoning_effort ?? latestApplied.reasoning_effort ?? unknown() }} · {{ label(verifications[latestApplied.verification]) }}</span>
    <span v-else>{{ t("AI 来源未记录") }}</span>
  </div>
  <details v-else class="ai-provenance panel" :open="records.length > 0">
    <summary>{{ t("AI 预填与复核记录") }}</summary>
    <p v-if="!records.length">{{ t("未记录模型与推理强度；这不表示该文章未经 AI 处理。") }}</p>
    <p v-else>{{ t("此处记录运行来源，不代表科学结论已通过审核。复核只针对所列候选文件。") }}</p>
    <p v-if="latestApplied && workspaceVersion && workspaceVersion > latestApplied.applied_workspace_version!">{{ t("当前工作区已有后续修改，不能将本次 AI 记录视为对当前全部内容的复核。") }}</p>
    <article v-for="record in records" :key="record.run_key" class="ai-run-record">
      <strong>{{ label(stages[record.stage]) }} · {{ label(outcomes[record.outcome]) }}</strong>
      <p>{{ t("请求模型") }}: <code>{{ record.model ?? unknown() }}</code> · {{ t("推理强度") }}: <code>{{ record.reasoning_effort ?? unknown() }}</code></p>
      <p v-if="record.observed_model">{{ t("请求记录中的模型") }}: <code>{{ record.observed_model }}</code> · {{ t("推理强度") }}: <code>{{ record.observed_reasoning_effort ?? unknown() }}</code></p>
      <p :class="{ 'validation-error': record.verification === 'mismatch' }">{{ label(verifications[record.verification]) }} · {{ record.adapter ?? unknown() }}<template v-if="record.applied_workspace_version"> · {{ t("导入版本") }} v{{ record.applied_workspace_version }}</template></p>
      <small v-if="record.completed_at">{{ formatDate(record.completed_at) }} · </small><small>{{ t("指南") }}: {{ record.guide_version ?? unknown() }}</small>
      <details><summary>{{ t("候选身份") }}</summary><code class="ai-run-hash">{{ record.candidate_file_sha256 }}</code><small>{{ record.run_key }}</small></details>
    </article>
  </details>
</template>
