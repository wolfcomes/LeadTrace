<script setup lang="ts">
import { computed } from 'vue';
import { locale,t } from '../../i18n';
import guide from '../help/reviewer-guide.json';
const props=defineProps<{section:string}>();
const entry=computed(()=>guide.sections.find(item=>item.id===props.section));
</script>
<template><details class="reviewer-help field-example"><summary>{{ t('填写示例（不会保存）') }}</summary><p>{{ locale === 'en' ? entry?.en : entry?.zh }}</p></details></template>
