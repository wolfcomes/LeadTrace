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
  <span class="verification-badge status-chip" :data-verification="status">{{ label }}</span>
</template>
