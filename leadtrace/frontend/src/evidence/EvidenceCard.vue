<script setup lang="ts">
import type { Evidence } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";


defineProps<{ evidence: Evidence }>();
</script>

<template>
  <article class="evidence-card">
    <div class="evidence-meta">
      <span :class="{ confirmed: evidence.state === 'confirmed' }">
        {{ evidence.state === "confirmed" ? zhCN.published.evidence.confirmed : zhCN.published.evidence.pending }}
      </span>
      <small>{{ zhCN.published.evidence.excerpt }}</small>
    </div>
    <blockquote>{{ evidence.text || "—" }}</blockquote>
    <code>{{ evidence.id }}</code>
  </article>
</template>

<style scoped>
.evidence-card { padding: 20px; border: 1px solid var(--line); border-radius: var(--radius-md); background: white; box-shadow: var(--shadow-sm); }
.evidence-meta { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.evidence-meta span { padding: 5px 9px; border-radius: 999px; color: var(--gold-700); background: var(--gold-100); font-size: .68rem; font-weight: 760; }
.evidence-meta span.confirmed { color: var(--forest-750); background: var(--forest-100); }
.evidence-meta small { color: var(--ink-500); font-size: .68rem; }
blockquote { margin: 18px 0; padding-left: 16px; border-left: 3px solid #d2b269; color: var(--ink-800); font: 400 1rem/1.7 Georgia, "Noto Serif SC Variable", serif; }
code { color: var(--ink-500); font: 500 .64rem/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
</style>
