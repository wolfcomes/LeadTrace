<script setup lang="ts">
import { computed } from "vue";
import { useReviewDisclosures } from "./reviewDisclosures";
const props = defineProps<{ id: string; label: string; expanded?: boolean }>();
const state = useReviewDisclosures();
const open = computed(() => state.get(props.id) ?? Boolean(props.expanded));
</script>
<template>
  <details :open="open" :data-disclosure="id" class="review-disclosure">
    <summary @click.prevent="state.set(id, !open)">
      {{ label }} <slot name="summary" />
    </summary>
    <div class="disclosure-content"><slot :open="open" /></div>
  </details>
</template>
<style scoped>
.review-disclosure {
  min-width: 0;
}
summary {
  cursor: pointer;
  color: var(--ink-muted);
  font-size: 0.85rem;
  padding: 0.45rem 0;
  overflow-wrap: anywhere;
}
summary:hover {
  color: var(--teal-deep);
}
.disclosure-content {
  min-width: 0;
}
</style>
