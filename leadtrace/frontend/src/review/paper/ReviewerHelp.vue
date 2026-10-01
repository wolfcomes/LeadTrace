<script setup lang="ts">
import { computed, ref } from 'vue';
import { locale, t } from '../../i18n';
import guide from '../help/reviewer-guide.json';
const search=ref('');
const english=computed(()=>locale.value==='en');
const groups=computed(()=>guide.groups.filter(x=>Object.values(x).join(' ').toLowerCase().includes(search.value.toLowerCase())));
</script>
<template><details class="reviewer-help" data-reviewer-help><summary>{{ t('Reviewer 指南与基团速查') }}</summary><div class="reviewer-help-content"><h2>{{ t('Reviewer 工作指南') }}</h2><p>{{ t('示例仅演示格式，不会自动填入记录。') }}</p><details v-for="section in guide.sections" :key="section.title_en"><summary>{{ english?section.title_en:section.title_zh }}</summary><p>{{ english?section.en:section.zh }}</p></details><h3>{{ t('基团缩写速查') }}</h3><label class="form-field">{{ t('搜索缩写或名称') }}<input v-model="search" placeholder="Me / Bn / Boc"></label><table><thead><tr><th>{{ t('缩写') }}</th><th>{{ t('含义') }}</th><th>{{ t('核对要点') }}</th></tr></thead><tbody><tr v-for="group in groups" :key="group.symbol"><td><code>{{ group.symbol }}</code></td><td>{{ english?group.en:group.zh }}</td><td>{{ english?group.note_en:group.note_zh }}</td></tr></tbody></table></div></details></template>
