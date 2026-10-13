<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { t } from "../i18n";
import type { Row, ScientificChange } from "./comparison";
import type { CompoundRecord } from "./recordComparison";
import { assetUrl, changeLabels, reviewState, textValue } from "./recordLabels";
import FrozenEvidence from "./FrozenEvidence.vue";
const props = defineProps<{
  record: CompoundRecord | null;
  snapshot: Record<string, unknown>;
  paperId: string;
  currentSourceSha: string;
  side: "before" | "after";
  changes: ScientificChange[];
  activityIds?: string[];
  available: boolean;
  compact?: boolean;
  memberRole?: unknown;
  absenceLabel?: string;
}>();
const failed = ref(new Set<string>());
watch(
  () => props.record,
  () => {
    failed.value = new Set();
  },
);
const activityRows = computed(
  () =>
    props.activityIds ??
    props.record?.activities.map((x) => String(x.id)) ??
    [],
);
function activity(id: string) {
  return props.record?.activities.find((x) => x.id === id);
}
function change(domain: string, id: unknown) {
  return props.changes.find((x) => x.domain === domain && x.id === id);
}
function isChanged(domain: string, id: unknown, key?: string) {
  const c = change(domain, id);
  return Boolean(c && (!key || c.fields.some((f) => f.key === key)));
}
function evidence(id: unknown) {
  return props.record?.evidence.find((x) => x.id === id);
}
function evidenceLabel(row: Row) {
  const c = change("evidence", row.id);
  return c ? changeLabels[c.kind] : "证据未变";
}
</script>
<template>
  <article
    class="frozen-compound-card"
    :class="{ compact }"
    :data-record-side="compact ? undefined : side"
    :data-compound-id="String(record?.compound.id ?? '')"
  >
    <header v-if="!compact" class="record-side-heading">
      <strong>{{ t(side === "before" ? "修改前" : "本次提交") }}</strong>
    </header>
    <template v-if="record">
      <section class="compound-identity">
        <p v-if="memberRole">
          {{ t("成员角色") }} · {{ reviewState(memberRole) }}
        </p>
        <div class="compound-heading">
          <h3>{{ record.compound.compound_label }}</h3>
          <span
            v-if="change('compounds', record.compound.id)"
            class="record-change-badge"
            >{{
              t(changeLabels[change("compounds", record.compound.id)!.kind])
            }}</span
          >
        </div>
        <p
          :class="{
            'field-modified': isChanged(
              'compounds',
              record.compound.id,
              'display_name',
            ),
          }"
        >
          {{ record.compound.display_name }}
        </p>
        <p
          :class="{
            'field-modified': isChanged(
              'compounds',
              record.compound.id,
              'description',
            ),
          }"
        >
          {{ record.compound.description }}
        </p>
        <p v-if="record.compound.review_hint" class="record-issue">
          {{ record.compound.review_hint }}
        </p>
        <p
          v-else-if="change('compounds', record.compound.id)?.issueResolution"
          class="record-resolved"
        >
          {{ t("核对提示已解决") }}
        </p>
        <div
          v-for="highlight in record.highlights"
          :key="String(highlight.id)"
          :class="{
            'field-modified': isChanged('compound_highlights', highlight.id),
          }"
        >
          <strong>{{
            reviewState(highlight.role ?? highlight.highlight_type)
          }}</strong>
          <p>{{ highlight.rationale ?? highlight.reason }}</p>
          <p>{{ t("适用范围") }} · {{ textValue(highlight.scope) }}</p>
          <p v-if="highlight.review_status">
            {{ reviewState(highlight.review_status) }}
          </p>
          <p v-if="highlight.review_hint" class="record-issue">
            {{ highlight.review_hint }}
          </p>
          <FrozenEvidence
            v-if="evidence(highlight.evidence_id)"
            :evidence="evidence(highlight.evidence_id)!"
            :snapshot="snapshot"
            :paper-id="paperId"
            :current-source-sha="currentSourceSha"
            :change-label="evidenceLabel(evidence(highlight.evidence_id)!)"
          />
        </div>
      </section>
      <section class="compound-structures">
        <h4>{{ t("分子结构") }}</h4>
        <article
          v-for="structure in record.structures"
          :key="String(structure.id)"
          :data-entity-type="'structures'"
          :class="{ 'field-modified': isChanged('structures', structure.id) }"
        >
          <div class="record-mini-heading">
            <span class="status-chip">{{ reviewState(structure.status) }}</span
            ><span
              v-if="change('structures', structure.id)"
              class="record-change-badge"
              >{{
                t(changeLabels[change("structures", structure.id)!.kind])
              }}</span
            >
          </div>
          <img
            v-if="
              structure.depiction_asset_id && !failed.has(String(structure.id))
            "
            data-rdkit-depiction
            :src="assetUrl(structure.depiction_asset_id)"
            :alt="t('RDKit 结构重绘')"
            @error="failed.add(String(structure.id))"
          />
          <p v-else class="structure-placeholder">
            {{
              t(
                structure.depiction_asset_id
                  ? "结构图片暂不可用"
                  : "当前结构没有可用的 RDKit 重绘图。",
              )
            }}
          </p>
          <details>
            <summary>{{ t("结构详细信息") }}</summary>
            <dl class="record-details">
              <template
                v-for="key in [
                  'canonical_smiles',
                  'smiles',
                  'inchi',
                  'inchikey',
                  'molfile',
                ]"
                :key="key"
                ><dt>
                  {{
                    key === "canonical_smiles"
                      ? "Canonical SMILES"
                      : key === "inchikey"
                        ? "InChIKey"
                        : key.toUpperCase()
                  }}
                </dt>
                <dd
                  :class="{
                    'field-modified': isChanged(
                      'structures',
                      structure.id,
                      key,
                    ),
                  }"
                >
                  {{ textValue(structure[key]) }}
                </dd></template
              >
            </dl>
          </details>
        </article>
        <p v-if="!record.structures.length" class="section-empty">
          {{ t("该化合物尚无结构记录。") }}
        </p>
      </section>
      <section v-if="!compact" class="compound-originals">
        <h4>{{ t("结构原文截图") }}</h4>
        <FrozenEvidence
          v-for="image in record.images"
          :key="String(image.id)"
          :evidence="image"
          :snapshot="snapshot"
          :paper-id="paperId"
          :current-source-sha="currentSourceSha"
          :change-label="
            change('structure_source_images', image.id)
              ? changeLabels[change('structure_source_images', image.id)!.kind]
              : '证据未变'
          "
        />
        <p v-if="!record.images.length" class="section-empty">
          {{ t("没有关联的结构原图。") }}
        </p>
      </section>
      <section v-if="!compact" class="compound-activities">
        <h4>{{ t("活性与实验条件") }}</h4>
        <article
          v-for="id in activityRows"
          :key="id"
          class="frozen-activity"
          :data-activity-id="id"
          :class="{ 'field-modified': isChanged('activities', id) }"
        >
          <div data-activity-content>
            <template v-if="activity(id)"
              ><div class="record-mini-heading">
                <strong>{{ activity(id)!.assay_name }}</strong
                ><span
                  v-if="change('activities', id)"
                  class="record-change-badge"
                  >{{ t(changeLabels[change("activities", id)!.kind]) }}</span
                >
              </div>
              <p class="activity-result">
                <span>{{ activity(id)!.metric }}</span
                ><strong
                  :class="{
                    'field-modified': isChanged('activities', id, 'value'),
                  }"
                  >{{ activity(id)!.operator }} {{ activity(id)!.value }}
                  {{ activity(id)!.unit }}</strong
                >
              </p>
              <p class="activity-context">
                <span>{{ t("实验条件") }}</span> ·
                {{ activity(id)!.context || "—" }}
              </p>
              <p v-if="activity(id)!.review_hint" class="record-issue">
                {{ activity(id)!.review_hint }}
              </p>
              <p
                v-else-if="change('activities', id)?.issueResolution"
                class="record-resolved"
              >
                {{ t("核对提示已解决") }}
              </p>
              <FrozenEvidence
                v-if="evidence(activity(id)!.evidence_id)"
                :evidence="evidence(activity(id)!.evidence_id)!"
                :snapshot="snapshot"
                :paper-id="paperId"
                :current-source-sha="currentSourceSha"
                :change-label="
                  evidenceLabel(evidence(activity(id)!.evidence_id)!)
                "
              />
              <p v-else class="section-empty">
                {{ t("无关联证据") }}
              </p></template
            >
            <p v-else class="record-absent">
              {{ t(side === "before" ? "修改前无此条目" : "本次提交已删除") }}
            </p>
          </div>
        </article>
        <p v-if="!activityRows.length" class="section-empty">
          {{ t("没有报告 Activity。") }}
        </p>
      </section>
    </template>
    <p v-else class="record-absent">
      {{
        t(
          !available && side === "before"
            ? "比较起点不可用，无法还原修改前条目。"
            : absenceLabel ||
                (side === "before" ? "修改前无此条目" : "本次提交已删除"),
        )
      }}
    </p>
  </article>
</template>
<style scoped>
.frozen-compound-card {
  min-width: 0;
  display: grid;
  grid-row: span 5;
  grid-template-rows: subgrid;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: var(--paper, white);
}
.frozen-compound-card > section {
  padding: 1rem;
  border-top: 1px solid var(--line);
  min-width: 0;
}
.record-side-heading {
  padding: 0.8rem 1rem;
  background: var(--slate-pale);
}
.frozen-compound-card[data-record-side="after"] > .record-side-heading {
  background: var(--teal-pale);
}
.compound-heading,
.record-mini-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.compound-heading h3 {
  margin: 0;
}
.frozen-compound-card h4 {
  margin: 0 0 0.7rem;
  color: var(--ink-muted);
  font-size: 0.85rem;
}
.frozen-compound-card p {
  overflow-wrap: anywhere;
  margin: 0.5rem 0;
}
.compound-structures img {
  width: 100%;
  height: 210px;
  object-fit: contain;
  background: white;
}
.structure-placeholder {
  height: 160px;
  display: grid;
  place-content: center;
  color: var(--ink-muted);
  background: var(--surface);
  text-align: center;
}
.field-modified {
  background: var(--amber-pale);
  border-radius: 4px;
}
.record-change-badge {
  font-size: 0.75rem;
  padding: 0.15rem 0.4rem;
  background: var(--amber-pale);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 4px;
}
.record-issue {
  border-left: 3px solid var(--amber-deep);
  padding: 0.5rem;
  background: var(--amber-pale);
}
.record-resolved {
  color: var(--teal-deep);
}
.record-details {
  font-size: 0.8rem;
}
.record-details dd {
  margin: 0 0 0.6rem;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.record-details dt {
  color: var(--ink-muted);
}
.frozen-activity {
  padding: 0.8rem;
  border: 1px solid var(--line);
  border-radius: 6px;
  margin: 0.75rem 0;
}
.activity-result {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
}
.activity-result strong {
  font-size: 1.2rem;
}
.activity-context {
  font-size: 0.85rem;
}
.record-absent {
  padding: 2rem 1rem;
  color: var(--ink-muted);
}
.compact {
  display: block;
}
.compact .compound-structures img {
  height: 160px;
}
summary {
  cursor: pointer;
  color: var(--ink-muted);
  font-size: 0.85rem;
}
</style>
