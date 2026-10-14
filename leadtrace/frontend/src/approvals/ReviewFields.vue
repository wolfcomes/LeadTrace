<script setup lang="ts">
import { computed } from "vue";
import type { Row } from "./comparison";
import { t } from "../i18n";
import { fieldLabels, reviewState, textValue } from "./recordLabels";
import { useReviewFocus } from "./reviewFocus";
import ReviewDisclosure from "./ReviewDisclosure.vue";
const props = defineProps<{
  row: Row;
  domain: string;
  fields: string[];
  recordId?: unknown;
  suffix?: string;
}>();
const focus = useReviewFocus();
const id = computed(() => props.recordId ?? props.row.id);
const groups = computed(() =>
  [true, false].map((changed) => ({
    changed,
    fields: props.fields.filter(
      (key) => focus.changed(props.domain, id.value, [key]) === changed,
    ),
  })),
);
function value(key: string) {
  return ["status", "review_status", "state", "role"].includes(key)
    ? reviewState(props.row[key])
    : textValue(props.row[key]);
}
</script>
<template>
  <div class="review-fields" :data-review-fields="`${domain}:${id}`">
    <template v-for="group in groups" :key="String(group.changed)">
      <component
        :is="group.changed ? 'div' : ReviewDisclosure"
        v-if="group.fields.length"
        :id="`unchanged:${domain}:${id}:${suffix ?? fields.join(',')}`"
        :label="t('未修改字段')"
      >
        <dl>
          <div
            v-for="key in group.fields"
            :key="key"
            :data-field="key"
            :class="{
              'field-modified': group.changed && focus.state.value.available,
            }"
          >
            <dt>{{ t(fieldLabels[key] ?? key) }}</dt>
            <dd>{{ value(key) }}</dd>
          </div>
        </dl>
      </component>
    </template>
  </div>
</template>
<style scoped>
dl {
  margin: 0.35rem 0;
}
dl > div {
  padding: 0.3rem 0.45rem;
}
dt {
  color: var(--ink-muted);
  font-size: 0.78rem;
}
dd {
  margin: 0.2rem 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 0.9rem;
}
.field-modified {
  background: var(--amber-pale);
  border-radius: 4px;
}
</style>
