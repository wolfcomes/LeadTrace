<script setup lang="ts">
import type { ChangeEvent } from "../v2/types";

defineProps<{ events: ChangeEvent[] }>();
function renderValue(value: Record<string, unknown> | null): string {
  return value === null ? "—" : JSON.stringify(value, null, 2);
}
function actorLabel(event: ChangeEvent): string {
  if (event.actor_kind === "ai") return "AI 预填";
  if (event.actor_kind === "reviewer") return "Reviewer";
  if (event.actor_kind === "admin") return "Admin";
  return "System";
}
</script>

<template>
  <section class="submission-diff panel" data-reviewer-diff>
    <div class="section-heading"><div><p class="eyebrow">AI → REVIEWER DIFF</p><h2>Reviewer 修改记录</h2></div><span>{{ events.length }} 项</span></div>
    <div v-if="events.length" class="submission-diff-list">
      <article v-for="event in events" :key="event.id">
        <header><strong>{{ event.entity_type }} · {{ event.action }}</strong><span class="status-chip">{{ actorLabel(event) }}</span></header>
        <code>{{ event.entity_id }}</code>
        <div class="submission-diff-values">
          <div><span>修改前</span><pre>{{ renderValue(event.before_value) }}</pre></div>
          <div><span>修改后</span><pre>{{ renderValue(event.after_value) }}</pre></div>
        </div>
      </article>
    </div>
    <p v-else class="section-empty">该 Submission 没有 Reviewer 修改记录。</p>
  </section>
</template>
