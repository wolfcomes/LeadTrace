<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { t } from "../i18n";
import type { Row, ScientificChange } from "./comparison";
import type { CompoundRecord } from "./recordComparison";
import { assetUrl, changeLabels, reviewState } from "./recordLabels";
import { useReviewFocus } from "./reviewFocus";
import ReviewFields from "./ReviewFields.vue";
import ReviewDisclosure from "./ReviewDisclosure.vue";
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
const focus = useReviewFocus();
function sectionChanged(section: string) {
  return (
    !props.available ||
    (section === "identity" &&
      props.memberRole !== undefined &&
      props.changes.some(
        (c) =>
          c.domain === "lineage_members" &&
          [c.before?.compound_id, c.after?.compound_id].includes(
            props.record?.compound.id,
          ),
      )) ||
    focus.compoundSection(props.record?.compound.id, section)
  );
}
function sectionOrder(section: string) {
  return (
    (sectionChanged(section) ? 0 : 10) +
    ["identity", "structures", "activities", "originals"].indexOf(section)
  );
}
const depictionFields = [
  "smiles",
  "canonical_smiles",
  "inchi",
  "inchikey",
  "molfile",
];
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
function activityChanged(id: string) {
  return !props.available || focus.related("activities", id);
}
function evidence(id: unknown) {
  return props.record?.evidence.find((x) => x.id === id);
}
function evidenceLabel(row: Row) {
  const c = change("evidence", row.id);
  return c
    ? changeLabels[c.kind]
    : props.available
      ? "证据未变"
      : "比较起点不可用";
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
      <section
        class="compound-identity"
        :data-section="'identity'"
        :data-priority="sectionChanged('identity') ? 0 : 1"
        :style="{ order: sectionOrder('identity') }"
      >
        <ReviewDisclosure
          class="ordered-disclosure"
          :id="`section:identity:${record.compound.id}`"
          :label="t('名称与说明')"
          :expanded="sectionChanged('identity')"
        >
          <template #summary
            ><span
              v-if="
                record.compound.review_hint ||
                record.highlights.some(
                  (h) => h.review_hint || h.review_status === 'unresolved',
                )
              "
              class="status-chip"
              >{{ t("待核对") }}</span
            ></template
          >

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
          <ReviewFields
            :style="{
              order: focus.changed('compounds', record.compound.id, [
                'display_name',
                'description',
              ])
                ? 0
                : 10,
            }"
            :row="record.compound"
            domain="compounds"
            :fields="['display_name', 'description']"
          />
          <ReviewFields
            :style="{
              order: isChanged('compounds', record.compound.id, 'review_hint')
                ? 0
                : 10,
            }"
            v-if="record.compound.review_hint"
            :row="record.compound"
            domain="compounds"
            :fields="['review_hint']"
          />
          <p
            v-if="
              !record.compound.review_hint &&
              change('compounds', record.compound.id)?.issueResolution
            "
            class="record-resolved"
          >
            {{ t("核对提示已解决") }}
          </p>
          <ReviewDisclosure
            v-for="highlight in focus.sortRows('compound_highlights', record.highlights)"
            :style="{
              order: focus.related('compound_highlights', highlight.id)
                ? 0
                : 10,
            }"
            :id="`highlight:${highlight.id}`"
            :label="reviewState(highlight.role ?? highlight.highlight_type)"
            :expanded="
              !available ||
              isChanged('compound_highlights', highlight.id) ||
              isChanged('evidence', highlight.evidence_id)
            "
            :key="String(highlight.id)"
            :class="{
              'field-modified': isChanged('compound_highlights', highlight.id),
            }"
          >
            <template #summary
              ><span
                v-if="
                  highlight.review_hint ||
                  highlight.review_status === 'unresolved'
                "
                class="status-chip"
                >{{ t("待核对") }}</span
              ></template
            >
            <ReviewFields
              :row="highlight"
              domain="compound_highlights"
              :fields="
                [
                  'role',
                  'rationale',
                  'reason',
                  'scope',
                  'review_status',
                  'review_hint',
                ].filter((k) => k in highlight)
              "
            />
            <FrozenEvidence
              v-if="evidence(highlight.evidence_id)"
              :evidence="evidence(highlight.evidence_id)!"
              :snapshot="snapshot"
              :paper-id="paperId"
              :current-source-sha="currentSourceSha"
              :change-label="evidenceLabel(evidence(highlight.evidence_id)!)"
            />
          </ReviewDisclosure>
        </ReviewDisclosure>
      </section>
      <section
        class="compound-structures"
        :data-section="'structures'"
        :data-priority="sectionChanged('structures') ? 0 : 1"
        :style="{ order: sectionOrder('structures') }"
      >
        <ReviewDisclosure
          :id="`section:structures:${record.compound.id}`"
          :label="t('分子结构')"
          :expanded="sectionChanged('structures')"
        >
          <template #summary
            ><span
              v-if="record.structures.some((s) => s.status === 'unresolved')"
              class="status-chip"
              >{{ t("未解决") }}</span
            ></template
          >

          <ReviewDisclosure
            v-for="structure in focus.sortRows('structures', record.structures)"
            :id="`structure:${structure.id}`"
            :label="
              t(
                isChanged('structures', structure.id)
                  ? '分子结构 · 有修改'
                  : !available
                    ? '分子结构'
                    : '分子结构 · 未修改',
              )
            "
            :expanded="!available || isChanged('structures', structure.id)"
            :key="String(structure.id)"
            class="ordered-disclosure"
            :data-entity-type="'structures'"
            :class="{ 'field-modified': isChanged('structures', structure.id) }"
          >
            <template #summary
              ><span
                v-if="structure.status === 'unresolved'"
                class="status-chip"
                >{{ t("未解决") }}</span
              ></template
            >
            <ReviewFields
              :row="structure"
              domain="structures"
              :style="{
                order: focus.changed('structures', structure.id, ['status'])
                  ? 0
                  : 10,
              }"
              :fields="['status','availability','availability_note','identity_source','checked_sources']"
            />
            <ReviewDisclosure
              :style="{
                order: focus.changed(
                  'structures',
                  structure.id,
                  depictionFields,
                )
                  ? 0
                  : 10,
              }"
              :id="`structure-depiction:${structure.id}`"
              :label="t('分子结构图')"
              :expanded="
                !available ||
                focus.changed('structures', structure.id, depictionFields)
              "
              v-slot="{ open: depictionOpen }"
            >
              <img
                v-if="
                  depictionOpen &&
                  structure.depiction_asset_id &&
                  !failed.has(String(structure.id))
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
            </ReviewDisclosure>
            <ReviewFields
              :row="structure"
              domain="structures"
              :style="{ order: 20 }"
              :fields="depictionFields"
            />
          </ReviewDisclosure>
          <p v-if="!record.structures.length" class="section-empty">
            {{ t("该化合物尚无结构记录。") }}
          </p>
        </ReviewDisclosure>
      </section>
      <section
        v-if="!compact"
        class="compound-originals"
        :data-section="'originals'"
        :data-priority="sectionChanged('originals') ? 0 : 1"
        :style="{ order: sectionOrder('originals') }"
      >
        <ReviewDisclosure
          :id="`section:originals:${record.compound.id}`"
          :label="t('结构原文截图')"
          :expanded="sectionChanged('originals')"
        >
          <FrozenEvidence
            v-for="image in focus.sortRows('structure_source_images', record.images)"
            :key="String(image.id)"
            :evidence="image"
            :snapshot="snapshot"
            :paper-id="paperId"
            :current-source-sha="currentSourceSha"
            :change-label="
              change('structure_source_images', image.id)
                ? changeLabels[
                    change('structure_source_images', image.id)!.kind
                  ]
                : !available
                  ? '比较起点不可用'
                  : '证据未变'
            "
          />
          <p v-if="!record.images.length" class="section-empty">
            {{ t("没有关联的结构原图。") }}
          </p>
        </ReviewDisclosure>
      </section>
      <section
        v-if="!compact"
        class="compound-activities"
        :data-section="'activities'"
        :data-priority="sectionChanged('activities') ? 0 : 1"
        :style="{ order: sectionOrder('activities') }"
      >
        <ReviewDisclosure
          :id="`section:activities:${record.compound.id}`"
          :label="t('活性与实验条件')"
          :expanded="sectionChanged('activities')"
        >
          <template #summary
            ><span
              v-if="
                record.activities.some(
                  (a) => a.review_hint || a.review_status === 'unresolved',
                )
              "
              class="status-chip"
              >{{ t("待核对") }}</span
            ></template
          >

          <article
            v-for="id in activityRows"
            :key="id"
            class="frozen-activity"
            :data-activity-id="id"
            :class="{ 'field-modified': isChanged('activities', id) }"
          >
            <div data-activity-content>
              <ReviewDisclosure
                v-if="activity(id)"
                :id="`activity:${id}`"
                :label="String(activity(id)!.assay_name || t('活性与实验条件'))"
                :expanded="activityChanged(id)"
                class="activity-disclosure"
              >
                <template #summary
                  ><span
                    v-if="
                      activity(id)!.review_hint ||
                      activity(id)!.review_status === 'unresolved'
                    "
                    class="status-chip"
                    >{{ t("待核对") }}</span
                  ><span class="status-chip">{{
                    t(
                      isChanged("activities", id)
                        ? changeLabels[change("activities", id)!.kind]
                        : isChanged("evidence", activity(id)!.evidence_id)
                          ? "证据更新"
                          : !available
                            ? "比较起点不可用"
                            : "未修改",
                    )
                  }}</span></template
                >
                <ReviewDisclosure
                  :id="`activity-result:${id}`"
                  :label="t('活性数值')"
                  :expanded="
                    !available ||
                    focus.changed('activities', id, [
                      'metric',
                      'operator',
                      'value',
                      'unit',
                    ])
                  "
                  :style="{
                    order: focus.changed('activities', id, [
                      'metric',
                      'operator',
                      'value',
                      'unit',
                    ])
                      ? 0
                      : 10,
                  }"
                >
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
                </ReviewDisclosure>
                <ReviewDisclosure
                  :style="{
                    order: focus.changed('activities', id, ['context'])
                      ? 0
                      : 10,
                  }"
                  :id="`activity-context:${id}`"
                  :label="t('实验条件')"
                  :expanded="
                    !available || isChanged('activities', id, 'context')
                  "
                >
                  <p class="activity-context">
                    <span>{{ t("实验条件") }}</span> ·
                    {{ activity(id)!.context || "—" }}
                  </p>
                </ReviewDisclosure>
                <ReviewFields
                  v-if="activity(id)!.review_hint"
                  :style="{
                    order: isChanged('activities', id, 'review_hint') ? 0 : 10,
                  }"
                  :row="activity(id)!"
                  domain="activities"
                  :fields="['review_hint']"
                />
                <p
                  v-if="
                    !activity(id)!.review_hint &&
                    change('activities', id)?.issueResolution
                  "
                  class="record-resolved"
                >
                  {{ t("核对提示已解决") }}
                </p>
                <FrozenEvidence
                  v-if="evidence(activity(id)!.evidence_id)"
                  :style="{
                    order:
                      focus.related('activities', id) &&
                      (isChanged('activities', id, 'evidence_id') ||
                        isChanged('evidence', activity(id)!.evidence_id))
                        ? 0
                        : 10,
                  }"
                  :evidence="evidence(activity(id)!.evidence_id)!"
                  :snapshot="snapshot"
                  :paper-id="paperId"
                  :current-source-sha="currentSourceSha"
                  :change-label="
                    isChanged('activities', id, 'evidence_id')
                      ? '证据更新'
                      : evidenceLabel(evidence(activity(id)!.evidence_id)!)
                  "
                />
                <p v-else class="section-empty">
                  {{ t("无关联证据") }}
                </p></ReviewDisclosure
              >
              <p v-else class="record-absent">
                {{ t(side === "before" ? "修改前无此条目" : "本次提交已删除") }}
              </p>
            </div>
          </article>
          <p v-if="!activityRows.length" class="section-empty">
            {{ t("没有报告 Activity。") }}
          </p>
        </ReviewDisclosure>
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
.activity-disclosure :deep(> .disclosure-content),
.ordered-disclosure :deep(> .disclosure-content) {
  display: flex;
  flex-direction: column;
}

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
  order: -10;
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
