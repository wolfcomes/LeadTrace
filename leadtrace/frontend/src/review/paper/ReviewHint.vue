<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";
import { t } from "../../i18n";

const props = defineProps<{ hint?: string | null }>();
const text = computed(() => props.hint?.trim() ?? "");
const expanded = ref(false);
const descriptionId = useId();
watch(text, () => { expanded.value = false; });
</script>

<template>
  <span v-if="text" class="review-hint" data-review-hint @click.stop>
    <button class="review-hint-toggle" type="button" :aria-label="t('需核对')" :title="t('需核对')" :aria-expanded="expanded" :aria-controls="descriptionId" @click="expanded = !expanded"><span aria-hidden="true">⚠</span></button>
    <span v-if="expanded" :id="descriptionId" class="review-hint-message" role="note">{{ text }}</span>
  </span>
</template>
