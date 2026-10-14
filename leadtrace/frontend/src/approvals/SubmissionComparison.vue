<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { t } from "../i18n";
import { buildRecordComparison, issueTarget } from "./recordComparison";
import {
  rows,
  type Comparison,
  type Row,
  type ScientificChange,
} from "./comparison";
import {
  changeLabels,
  domainLabels,
  fieldLabels,
  reviewState,
  textValue,
} from "./recordLabels";
import { usePairedActivityAlignment } from "./usePairedActivityAlignment";
import { useFrozenPdfPool } from "./frozenPdf";
import { provideReviewFocus } from "./reviewFocus";
import ReviewDisclosure from "./ReviewDisclosure.vue";
import { provideReviewDisclosures } from "./reviewDisclosures";
import FrozenCompoundCard from "./FrozenCompoundCard.vue";
import FrozenEvidence from "./FrozenEvidence.vue";
import LineageRecordComparison from "./LineageRecordComparison.vue";
import ResearchProfileComparison from "./ResearchProfileComparison.vue";
import type { ResearchProfile } from "../review/paper/articleMetadata";
const props = defineProps<{
  snapshot: Record<string, unknown>;
  comparison?: Comparison;
  paperId: string;
}>();
useFrozenPdfPool();
const disclosures = provideReviewDisclosures();
const result = computed(() =>
  buildRecordComparison(props.snapshot, props.comparison),
);
provideReviewFocus(
  computed(() => ({
    available: result.value.available,
    changes: result.value.changes,
    before: props.comparison?.baseline_snapshot ?? {},
    after: props.snapshot,
  })),
);
const baseline = computed(() => props.comparison?.baseline_snapshot ?? {}),
  sourceSha = computed(() =>
    String((props.snapshot.source as Row | undefined)?.sha256 ?? ""),
  );
const tab = ref<"article" | "compounds" | "lineages">("compounds"),
  changedOnly = ref(true),
  selected = ref(""),
  navOpen = ref(true),
  selectedEntity = ref("");
watch(
  () => [props.snapshot, selected.value, tab.value],
  () => disclosures.clear(),
);
const tabs = [
  { key: "article", label: "文章信息" },
  { key: "compounds", label: "化合物与结构" },
  { key: "lineages", label: "Lineage" },
] as const;
const records = computed(() =>
  tab.value === "article"
    ? [result.value.article]
    : tab.value === "compounds"
      ? result.value.compounds
      : result.value.lineages,
);
const entries = computed(() =>
  records.value.filter(
    (x) => !changedOnly.value || !result.value.available || x.changed,
  ),
);
const selectedCompound = computed(() =>
  result.value.compounds.find((x) => x.id === selected.value),
);
const selectedLineage = computed(() =>
  result.value.lineages.find((x) => x.id === selected.value),
);
const selectedRecord = computed(() =>
  records.value.find((x) => x.id === selected.value),
);
const activityIds = computed(() =>
  [
    ...new Set(
      [
        ...(selectedCompound.value?.before?.activities ?? []),
        ...(selectedCompound.value?.after?.activities ?? []),
      ].map((x) => String(x.id)),
    ),
  ].sort(
    (a, b) => Number(activityHasChanges(b)) - Number(activityHasChanges(a)),
  ),
);
function activityHasChanges(id: string) {
  const evidenceIds = [baseline.value, props.snapshot].flatMap((s) =>
    rows(s, "activities")
      .filter((r) => r.id === id)
      .map((r) => r.evidence_id),
  );
  return result.value.changes.some(
    (c) =>
      (c.domain === "activities" && c.id === id) ||
      (c.domain === "evidence" && evidenceIds.includes(c.id)),
  );
}
const sides = ["before", "after"] as const;
const compoundPair = ref<HTMLElement>();
usePairedActivityAlignment(compoundPair, () => [selected.value, tab.value]);
watch(
  () => props.snapshot,
  () => {
    tab.value = result.value.compounds.some((x) => x.changed)
      ? "compounds"
      : result.value.lineages.some((x) => x.changed)
        ? "lineages"
        : result.value.article.changed
          ? "article"
          : "compounds";
    selected.value = "";
  },
  { immediate: true },
);
watch(
  entries,
  (list) => {
    if (!list.some((x) => x.id === selected.value))
      selected.value = list[0]?.id ?? "";
  },
  { immediate: true },
);
function count(key: string) {
  return key === "article"
    ? Number(result.value.article.changed)
    : (key === "compounds"
        ? result.value.compounds
        : result.value.lineages
      ).filter((x) => x.changed).length;
}
function description(changes: ScientificChange[]) {
  return [
    ...new Set(changes.map((x) => t(domainLabels[x.domain] ?? x.domain))),
  ].join(" · ");
}
function issueNavigate(issue: { id: string; domain: string }) {
  const target = issueTarget(props.snapshot, issue);
  changedOnly.value = false;
  tab.value = target.tab;
  selected.value = target.recordId;
  selectedEntity.value = target.selection;
}
const articleDomains = computed(() =>
  ["paper", "sections", "source"].sort(
    (a, b) =>
      Number(result.value.article.changes.some((c) => c.domain === b)) -
      Number(result.value.article.changes.some((c) => c.domain === a)),
  ),
);
function evidenceForArticle(snapshot: Record<string, unknown>) {
  const linkedIds = new Set(
    [
      ...rows(snapshot, "activities"),
      ...rows(snapshot, "compound_highlights"),
      ...rows(snapshot, "edge_evidence_links"),
    ].map((x) => x.evidence_id),
  );
  return rows(snapshot, "evidence").filter((x) => !linkedIds.has(x.id)).sort((a,b) => Number(result.value.changes.some(c => c.domain === 'evidence' && c.id === b.id))-Number(result.value.changes.some(c => c.domain === 'evidence' && c.id === a.id)));
}
function visibleFields(row: Row) {
  return Object.entries(row).filter(
    ([key]) =>
      ![
        "id",
        "paper_id",
        "workspace_id",
        "asset_id",
        "catalog_state",
        "created_at",
        "updated_at",
        "created_by_kind",
        "created_by_id",
      ].includes(key),
  );
}
function articleFields(row: Row, domain: string, changed: boolean) {
  const pairedRow = domain === 'paper' && (
    rows(props.snapshot, 'paper')[0]?.research_profile || rows(baseline.value, 'paper')[0]?.research_profile
  ) ? { ...row, research_profile: row.research_profile ?? {} } : row;
  return visibleFields(pairedRow).filter(
    ([key]) =>
      (!result.value.available ||
        fieldChanged(domain, row.section_key ?? row.id, key)) === changed,
  );
}
function fieldChanged(domain: string, id: unknown, key: string) {
  return result.value.article.changes.some(
    (x) =>
      x.domain === domain &&
      (domain === "paper" || domain === "source" || x.id === id) &&
      x.fields.some((f) => f.key === key),
  );
}
</script>
<template>
  <section class="submission-comparison panel" data-comparison-summary>
    <header class="section-heading">
      <div>
        <p class="eyebrow">FROZEN RECORD COMPARISON</p>
        <h2>{{ t("本次提交修改") }}</h2>
      </div>
    </header>
    <p v-if="comparison?.kind === 'previous_submission' && result.available">
      {{
        t("比较起点：第 {number} 次提交", {
          number: comparison.baseline_submission_number ?? "—",
        })
      }}
    </p>
    <p v-else-if="comparison?.kind === 'reviewer_start' && result.available">
      {{ t("比较起点：Reviewer 开始本轮审核时的内容") }}
    </p>
    <p class="comparison-explainer">
      {{ t("展示起点与冻结提交之间的净变化；完整提交仍是批准对象。") }}
    </p>
    <p
      v-for="warning in result.warnings"
      :key="warning"
      class="message is-error"
      data-comparison-warning
      role="alert"
    >
      {{ t(warning) }}
    </p>
    <div v-if="result.available" class="comparison-counts">
      <strong>{{
        t("{count} 个化合物有修改", { count: count("compounds") })
      }}</strong
      ><strong>{{
        t("{count} 个 Lineage 受影响", { count: count("lineages") })
      }}</strong
      ><span>{{
        t("{count} 项实质修改", { count: result.changes.length })
      }}</span>
    </div>
    <details
      v-if="result.issues.length"
      class="remaining-issues"
      data-remaining-issues
    >
      <summary>{{ t("仍需核对的问题") }} · {{ result.issues.length }}</summary>
      <ul>
        <li v-for="(issue, index) in result.issues" :key="index">
          <button
            type="button"
            class="button-quiet"
            @click="issueNavigate(issue)"
          >
            {{ t(domainLabels[issue.domain] ?? issue.domain) }} ·
            {{ issue.label }}
          </button>
          — {{ reviewState(issue.detail) }}
        </li>
      </ul>
    </details>
    <div class="record-browser-toolbar">
      <nav class="record-tabs" :aria-label="t('审核分区')">
        <button
          v-for="item in tabs"
          :key="item.key"
          type="button"
          :data-record-tab="item.key"
          :aria-pressed="tab === item.key"
          :class="{ 'is-active': tab === item.key }"
          @click="tab = item.key"
        >
          {{ t(item.label)
          }}<span v-if="result.available">{{ count(item.key) }}</span>
        </button>
      </nav>
      <label class="record-filter"
        ><input
          v-model="changedOnly"
          type="checkbox"
          data-change-only
          :disabled="!result.available"
        />{{ t("仅看有修改的条目") }}</label
      >
    </div>
    <p
      v-if="result.available && !result.changes.length"
      class="section-empty"
      data-no-scientific-changes
    >
      {{ t("本次没有实质内容修改。请结合未解决问题及完整提交决定是否批准。") }}
    </p>
    <div class="record-browser" :class="{ 'navigation-collapsed': !navOpen }">
      <aside class="record-navigation">
        <button
          class="button-quiet navigation-toggle"
          type="button"
          data-record-navigation-toggle
          :aria-expanded="navOpen"
          @click="navOpen = !navOpen"
        >
          {{ t(navOpen ? "收起条目目录" : "展开条目目录") }}
        </button>
        <nav v-if="navOpen" :aria-label="t('条目目录')">
          <button
            v-for="record in entries"
            :key="record.id"
            type="button"
            :data-record-entry="record.id"
            :aria-current="selected === record.id ? 'true' : undefined"
            :class="{ 'is-selected': selected === record.id }"
            @click="selected = record.id"
          >
            <strong>{{
              tab === "article" ? t(record.label) : record.label
            }}</strong
            ><span>{{ t(changeLabels[record.kind]) }}</span
            ><small v-if="record.changed">{{
              description(record.changes)
            }}</small>
          </button>
          <p v-if="!entries.length" class="section-empty">
            {{ t("此分区没有修改条目，可取消筛选查看全部。") }}
          </p>
        </nav>
      </aside>
      <main
        class="record-main"
        v-if="selectedRecord"
        data-change-card
        :data-record-id="selectedRecord.id"
      >
        <header class="record-change-summary">
          <strong>{{
            tab === "article" ? t(selectedRecord.label) : selectedRecord.label
          }}</strong
          ><span class="status-chip">{{
            t(changeLabels[selectedRecord.kind])
          }}</span>
          <p v-if="selectedRecord.changes.length">
            {{ description(selectedRecord.changes) }}
          </p>
          <span
            v-if="selectedRecord.changes.some((x) => x.issueResolution)"
            class="status-chip"
            >{{ t("问题处理") }}</span
          >
        </header>
        <div
          v-if="tab === 'compounds' && selectedCompound"
          ref="compoundPair"
          class="paired-compound-records"
        >
          <FrozenCompoundCard
            v-for="side in sides"
            :key="side"
            :record="selectedCompound[side]"
            :snapshot="side === 'before' ? baseline : snapshot"
            :paper-id="paperId"
            :current-source-sha="sourceSha"
            :side="side"
            :changes="selectedCompound.changes"
            :activity-ids="activityIds"
            :available="result.available"
          />
        </div>
        <LineageRecordComparison
          v-else-if="tab === 'lineages' && selectedLineage"
          :key="selectedLineage.id"
          :record="selectedLineage"
          :initial-selection="selectedEntity"
          :before="baseline"
          :after="snapshot"
          :paper-id="paperId"
          :current-source-sha="sourceSha"
          :available="result.available"
        />
        <div v-else-if="tab === 'article'" class="paired-article-records">
          <article v-for="side in sides" :key="side" :data-record-side="side">
            <h3 class="record-side-heading">
              {{ t(side === "before" ? "修改前" : "本次提交") }}
            </h3>
            <template v-if="side === 'after' || result.available"
              ><section
                :style="{
                  order: result.article.changes.some((c) => c.domain === domain)
                    ? 0
                    : 10,
                }"
                v-for="domain in articleDomains"
                :key="domain"
              >
                <h4>{{ t(domainLabels[domain]) }}</h4>
                <div
                  v-for="row in rows(
                    side === 'before' ? baseline : snapshot,
                    domain,
                  )"
                  :key="String(row.id ?? row.section_key ?? domain)"
                >
                  <template
                    v-for="changed in [true, false]"
                    :key="String(changed)"
                  >
                    <ReviewDisclosure
                      v-if="articleFields(row, domain, changed).length"
                      :id="`article:${domain}:${row.id ?? row.section_key ?? domain}:${changed}`"
                      :label="
                        t(
                          !result.available
                            ? '完整内容'
                            : changed
                              ? '已修改字段'
                              : '未修改字段',
                        )
                      "
                      :expanded="changed"
                    >
                      <dl class="article-details">
                        <template
                          v-for="[key, value] in articleFields(
                            row,
                            domain,
                            changed,
                          )"
                          :key="key"
                          ><dt>{{ t(fieldLabels[key] ?? key) }}</dt>
                          <dd
                            :class="{
                              'field-modified': key !== 'research_profile' && fieldChanged(
                                domain,
                                row.section_key ?? row.id,
                                key,
                              ),
                            }"
                          >
                            <ResearchProfileComparison v-if="key === 'research_profile'" :profile="(value ?? {}) as ResearchProfile" :other="(rows(side === 'before' ? snapshot : comparison?.baseline_snapshot ?? {}, 'paper')[0]?.research_profile ?? {}) as ResearchProfile" :available="result.available" />
                            <template v-else>{{
                              ["state", "status", "section_key", "abstract_status"].includes(key)
                                ? reviewState(value)
                                : textValue(value)
                            }}</template>
                          </dd></template
                        >
                      </dl>
                    </ReviewDisclosure>
                  </template>
                </div>
              </section>
              <section
                :style="{
                  order: result.article.changes.some(
                    (c) => c.domain === 'evidence',
                  )
                    ? 0
                    : 10,
                }"
              >
                <h4>{{ t("其他原文证据") }}</h4>
                <FrozenEvidence
                  v-for="evidence in evidenceForArticle(
                    side === 'before' ? baseline : snapshot,
                  )"
                  :key="String(evidence.id)"
                  :evidence="evidence"
                  :change-label="
                    result.article.changes.some(
                      (c) => c.domain === 'evidence' && c.id === evidence.id,
                    )
                      ? '证据更新'
                      : !result.available
                        ? '比较起点不可用'
                        : '证据未变'
                  "
                  :snapshot="side === 'before' ? baseline : snapshot"
                  :paper-id="paperId"
                  :current-source-sha="sourceSha"
                /></section
            ></template>
            <p v-else class="section-empty">
              {{ t("比较起点不可用，无法还原修改前条目。") }}
            </p>
          </article>
        </div>
        <details
          v-if="selectedRecord.changes.length"
          class="record-field-details"
        >
          <summary>
            {{ t("修改明细与来源") }} · {{ selectedRecord.changes.length }}
          </summary>
          <article
            v-for="change in selectedRecord.changes"
            :key="`${change.domain}:${change.id}`"
            class="field-detail"
          >
            <header>
              <strong
                >{{ t(domainLabels[change.domain] ?? change.domain) }} ·
                {{ change.label }}</strong
              >
              · {{ t(changeLabels[change.kind]) }}
            </header>
            <p>
              {{ t("修改来源") }}:
              {{
                change.actors.length
                  ? change.actors
                      .map((x) =>
                        x === "ai"
                          ? "AI"
                          : x === "reviewer"
                            ? "Reviewer"
                            : x === "admin"
                              ? "Admin"
                              : "System",
                      )
                      .join(" · ")
                  : t("未记录")
              }}
            </p>
            <dl>
              <template v-for="field in change.fields" :key="field.key"
                ><dt>{{ t(fieldLabels[field.key] ?? field.key) }}</dt>
                <dd>
                  {{
                    ["status", "review_status", "state"].includes(field.key)
                      ? reviewState(field.before)
                      : textValue(field.before)
                  }}
                  →
                  {{
                    ["status", "review_status", "state"].includes(field.key)
                      ? reviewState(field.after)
                      : textValue(field.after)
                  }}
                </dd></template
              >
            </dl>
          </article>
        </details>
      </main>
      <div v-else class="record-main section-empty">
        {{ t("选择一个条目，查看完整内容和左右变化。") }}
      </div>
    </div>
    <details
      v-if="result.available"
      class="confirmation-summary"
      data-confirmation-summary
    >
      <summary>
        {{
          t("另有 {count} 项仅确认、内容未变", {
            count: result.confirmations.length,
          })
        }}
      </summary>
      <ul>
        <li
          v-for="change in result.confirmations"
          :key="`${change.domain}:${change.id}`"
        >
          {{ t(domainLabels[change.domain] ?? change.domain) }} ·
          {{ change.label
          }}<span v-for="field in change.fields" :key="field.key">
            · {{ reviewState(field.before) }} →
            {{ reviewState(field.after) }}</span
          >
        </li>
      </ul>
    </details>
  </section>
</template>
<style scoped>
.paired-article-records > article {
  display: flex;
  flex-direction: column;
}
.paired-article-records .record-side-heading {
  order: -10;
}
.submission-comparison {
  padding: 1.25rem;
}
.comparison-explainer {
  color: var(--ink-muted);
  font-size: 0.85rem;
}
.comparison-counts {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  padding: 0.7rem 0;
  font-size: 0.9rem;
}
.comparison-counts strong {
  font-weight: 600;
}
.remaining-issues {
  background: var(--amber-pale);
  padding: 0.7rem 1rem;
  border-left: 3px solid var(--amber-deep);
  margin: 0.7rem 0;
}
.remaining-issues summary {
  font-weight: 600;
  cursor: pointer;
}
.record-browser-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--line);
  margin: 1rem 0;
}
.record-tabs {
  display: flex;
  gap: 0.25rem;
}
.record-tabs button {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  border: 0;
  border-bottom: 3px solid transparent;
  background: none;
  padding: 0.8rem 0.9rem;
  cursor: pointer;
  font-weight: 600;
  color: var(--ink-muted);
}
.record-tabs button.is-active {
  border-color: var(--teal-deep);
  color: var(--teal-deep);
}
.record-tabs span {
  font-size: 0.75rem;
  padding: 0.1rem 0.35rem;
  background: var(--slate-pale);
  border-radius: 4px;
}
.record-filter {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  padding: 0.5rem 0;
}
.record-browser {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 1rem;
}
.record-browser.navigation-collapsed {
  grid-template-columns: 1fr;
}
.navigation-collapsed .record-navigation {
  border: 0;
}
.record-navigation {
  border-right: 1px solid var(--line);
  padding-right: 0.75rem;
  min-width: 0;
}
.navigation-toggle {
  font-size: 0.8rem;
  padding: 0.4rem 0;
}
.record-navigation nav {
  display: grid;
  gap: 0.5rem;
}
.record-navigation nav > button {
  display: flex;
  flex-wrap: wrap;
  text-align: left;
  gap: 0.35rem;
  width: 100%;
  padding: 0.7rem;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--paper, white);
  cursor: pointer;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.record-navigation nav > button strong {
  width: 100%;
  font-size: 0.9rem;
}
.record-navigation nav > button span,
.record-navigation nav > button small {
  font-size: 0.75rem;
  color: var(--ink-muted);
}
.record-navigation nav > button.is-selected {
  border-color: var(--teal-deep);
  background: var(--teal-pale);
}
.record-main {
  min-width: 0;
}
.record-change-summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0 0 0.75rem;
}
.record-change-summary > strong {
  font-size: 1.1rem;
}
.record-change-summary p {
  font-size: 0.8rem;
  color: var(--ink-muted);
  margin: 0;
}
.paired-compound-records,
.paired-article-records {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.8rem;
}
.paired-article-records > article {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}
.record-side-heading {
  margin: 0;
  padding: 0.75rem 1rem;
  background: var(--slate-pale);
  font-size: 0.9rem;
}
.paired-article-records > article:last-child > .record-side-heading {
  background: var(--teal-pale);
}
.paired-article-records section {
  padding: 1rem;
  border-top: 1px solid var(--line);
}
.article-details {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  gap: 0.4rem;
  font-size: 0.85rem;
}
.article-details dt {
  color: var(--ink-muted);
}
.article-details dd {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.field-modified {
  background: var(--amber-pale);
}
.record-field-details {
  margin: 1rem 0;
  border-top: 1px solid var(--line);
  padding: 0.8rem 0;
  font-size: 0.85rem;
}
.record-field-details summary {
  cursor: pointer;
  color: var(--ink-muted);
}
.field-detail {
  padding: 0.7rem 0;
  border-bottom: 1px solid var(--line);
}
.field-detail p {
  color: var(--ink-muted);
}
.field-detail dl {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 0.4rem;
}
.field-detail dd {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.confirmation-summary {
  margin-top: 1rem;
  padding: 0.8rem;
  background: var(--slate-pale);
  font-size: 0.85rem;
}
.confirmation-summary summary {
  cursor: pointer;
}
@media (max-width: 1100px) {
  .record-browser {
    grid-template-columns: 145px minmax(0, 1fr);
    gap: 0.7rem;
  }
}
@media (max-width: 800px) {
  .record-browser {
    grid-template-columns: 1fr;
  }
  .record-navigation {
    border: 0;
    padding: 0;
  }
  .record-navigation nav {
    display: flex;
    overflow-x: auto;
    padding: 0.3rem 0;
  }
  .record-navigation nav > button {
    min-width: 160px;
    width: 160px;
    flex-shrink: 0;
  }
  .paired-compound-records,
  .paired-article-records {
    grid-template-columns: repeat(2, minmax(280px, 1fr));
    overflow-x: auto;
  }
  .record-tabs button {
    padding: 0.7rem 0.5rem;
  }
  .submission-comparison {
    padding: 0.7rem;
  }
  .article-details {
    grid-template-columns: 1fr;
  }
}
</style>
