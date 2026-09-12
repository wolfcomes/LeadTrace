<script setup lang="ts">
defineProps<{ loading: boolean; error: string | null }>();
</script>
<template><section v-if="loading" class="page-state"><span class="state-spinner" aria-hidden="true"></span><p>正在加载…</p></section><section v-else-if="error" class="page-state"><span class="state-symbol is-error" aria-hidden="true">!</span><h2>暂时无法读取</h2><p>{{ error }}</p></section><slot v-else /></template>
