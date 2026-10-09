<script setup lang="ts">
import { t } from "../../i18n";
import ReviewHint from "./ReviewHint.vue";
import { computed, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import { structureDepictionUrl } from '../../v2/api';
import type { Compound } from '../../v2/types';
import type { LineageStructureState } from './useLineageStructures';
const props = defineProps<{ compound?: Compound; compoundId: string; state?: LineageStructureState; workspaceId: string; paperId: string; caption: string }>();
const emit = defineEmits<{ retry: [compoundId: string] }>();
const imageFailed = ref(false);
const structure = computed(() => props.state?.structure);
const depictionUrl = computed(() => structureDepictionUrl(props.compoundId, structure.value?.depiction_asset_id));
watch(depictionUrl, () => { imageFailed.value = false; });
const statusText = computed(() => ({ draft: '结构草稿', reviewer_confirmed: '结构已确认', unresolved: '结构待解决', not_reported: '未报告结构' }[structure.value?.status || 'draft']));
const to = computed(() => ({ path: `/review/papers/${props.paperId}`, query: { workspace: props.workspaceId, tab: 'compounds', entity: props.compoundId } }));
</script>
<template>
  <article class="edge-compound-card" data-edge-endpoint :data-compound-id="compoundId">
    <header><span>{{ caption }}</span><strong>Compound {{ compound?.compound_label || '?' }}</strong><ReviewHint :hint="compound?.review_hint" /><span v-if="structure" class="status-chip">{{ t(statusText) }}</span></header>
    <p v-if="!state || state.status === 'loading'" class="endpoint-placeholder">{{ t("正在读取结构…") }}</p>
    <p v-else-if="state.status === 'error'" class="endpoint-placeholder" role="alert">{{ t("结构暂时无法读取。") }}<button class="button-quiet" type="button" @click="emit('retry', compoundId)">{{ t("重试") }}</button></p>
    <img v-else-if="structure?.depiction_asset_id && !imageFailed" data-endpoint-depiction :src="depictionUrl" :alt="t('Compound {p0} 的 RDKit 结构重绘', { p0: compound?.compound_label || '?' })" @error="imageFailed = true">
    <p v-else class="endpoint-placeholder">{{ imageFailed ? t("结构图片暂不可用，可进入化合物详情核对。") : structure ? t("当前结构没有可用的 RDKit 重绘图。") : t("该化合物尚无结构记录。") }}</p>
    <p v-if="compound?.display_name">{{ compound.display_name }}</p>
    <details v-if="compound?.description || structure?.canonical_smiles || structure?.smiles"><summary>{{ t("化合物说明与 SMILES") }}</summary><p v-if="compound?.description">{{ compound.description }}</p><code>{{ structure?.canonical_smiles || structure?.smiles }}</code></details>
    <RouterLink class="button-secondary" data-endpoint-compound-link :to="to">{{ t("查看化合物、原图与活性 →") }}</RouterLink>
  </article>
</template>
