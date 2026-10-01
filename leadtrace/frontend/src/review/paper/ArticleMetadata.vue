<script setup lang="ts">
import { t } from '../../i18n';
import type { PdbReference } from '../../v2/workbench';
import ReviewHint from './ReviewHint.vue';
defineProps<{metadata:{abstract?:string|null;abstract_source?:string|null;pdb_references?:PdbReference[]}}>();
const usageLabels = {this_work:'本文结构',cited_structure:'引用结构',unknown:'用途待核对'};
</script>
<template><section class="article-metadata"><h3>Abstract</h3><p class="preserve-lines" data-article-abstract>{{ metadata.abstract || t('尚未记录摘要') }}</p><small v-if="metadata.abstract_source">{{ t('摘要来源') }}：{{ metadata.abstract_source }}</small><h3>PDB</h3><p v-if="!metadata.pdb_references?.length">{{ t('尚未记录 PDB ID；空白不表示文章一定未报告。') }}</p><ul v-else><li v-for="(entry,index) in metadata.pdb_references" :key="index"><a :href="`https://www.rcsb.org/structure/${encodeURIComponent(entry.pdb_id)}`" target="_blank" rel="noopener">{{ entry.pdb_id }} ↗</a> · {{ t(usageLabels[entry.usage]) }}<span v-if="entry.source_page"> · p. {{ entry.source_page }}</span><span v-if="entry.compound_label"> · Compound {{ entry.compound_label }}</span><p v-if="entry.source_context">{{ entry.source_context }}</p><ReviewHint :hint="entry.review_hint" /></li></ul></section></template>
