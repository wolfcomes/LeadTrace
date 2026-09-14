<script setup lang="ts">
import type { Evidence } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";


defineProps<{ evidence: Evidence }>();
</script>

<template>
  <article class="evidence-card panel">
    <div class="evidence-meta">
      <span :class="['status-chip', evidence.state === 'confirmed' ? 'is-ok' : 'is-warning']">
        {{ evidence.state === "confirmed" ? zhCN.published.evidence.confirmed : zhCN.published.evidence.pending }}
      </span>
      <small>{{ zhCN.published.evidence.excerpt }}</small>
    </div>
    <blockquote>{{ evidence.text || "—" }}</blockquote>
    <code>{{ evidence.id }}</code>
  </article>
</template>
