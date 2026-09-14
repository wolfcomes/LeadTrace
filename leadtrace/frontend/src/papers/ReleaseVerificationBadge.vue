<script setup lang="ts">
import { computed } from "vue";

import type { ReleaseMetadata } from "../api/schema";


const props = defineProps<{
  status: ReleaseMetadata["verification_status"];
}>();

const label = computed(() => ({
  unverified: "未验证",
  partially_verified: "部分已核验",
  human_verified: "已人工核验",
})[props.status]);
</script>

<template>
  <span class="verification-badge" :data-verification="status">{{ label }}</span>
</template>

<style scoped>
.verification-badge { display: inline-flex; width: max-content; margin-top: 8px; padding: 4px 8px; border-radius: 999px; color: #8b3d2f; background: #fbe9e3; font-size: .65rem; font-weight: 750; }
.verification-badge[data-verification="partially_verified"] { color: #725d2b; background: #f7efd9; }
.verification-badge[data-verification="human_verified"] { color: #1f674c; background: #e4f3eb; }
</style>
