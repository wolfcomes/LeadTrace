<script setup lang="ts">
import { locale,t } from '../../i18n';
import guide from '../help/reviewer-guide.json';
defineProps<{section:number}>();
</script>
<template><details class="reviewer-help field-example"><summary>{{ t('填写示例（不会保存）') }}</summary><p>{{ locale === 'en' ? guide.sections[section]?.en : guide.sections[section]?.zh }}</p></details></template>
