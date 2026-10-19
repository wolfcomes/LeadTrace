import type { Activity } from '../../v2/types';

export interface MeasurementColumn {
  key: string;
  assay: string;
  metric: string;
  unit: string | null;
  context: string | null;
}
export function measurementKey(activity: Activity): string {
  return JSON.stringify([activity.assay_name, activity.metric, activity.unit, activity.context]);
}
export function activityMatrix(activities: Activity[]) {
  const columns = new Map<string, MeasurementColumn>();
  const cells = new Map<string, Map<string, Activity[]>>();
  for (const activity of activities) {
    const key = measurementKey(activity);
    if (!columns.has(key)) columns.set(key, {key, assay: activity.assay_name, metric: activity.metric, unit: activity.unit, context: activity.context});
    let compound = cells.get(activity.compound_id);
    if (!compound) { compound = new Map(); cells.set(activity.compound_id, compound); }
    const observations = compound.get(key) ?? [];
    observations.push(activity);
    compound.set(key, observations);
  }
  return {columns: [...columns.values()], cells};
}

export interface MeasurementGroup {
  key: string;
  assay: string;
  metric: string;
  unit: string | null;
  compoundCount: number;
  columns: Array<MeasurementColumn & {compoundCount: number}>;
}
const labelOrder = new Intl.Collator('en', {numeric: true, sensitivity: 'base'});
function stableText(a: string, b: string): number {
  return labelOrder.compare(a, b) || (a < b ? -1 : a > b ? 1 : 0);
}
export function measurementGroups(activities: Activity[]): MeasurementGroup[] {
  const groups = new Map<string, {group: MeasurementGroup; compounds: Set<string>; coverage: Map<string, Set<string>>}>();
  for (const activity of activities) {
    const key = JSON.stringify([activity.assay_name, activity.metric, activity.unit]);
    let entry = groups.get(key);
    if (!entry) {
      entry = {group: {key, assay: activity.assay_name, metric: activity.metric, unit: activity.unit, compoundCount: 0, columns: []}, compounds: new Set(), coverage: new Map()};
      groups.set(key, entry);
    }
    entry.compounds.add(activity.compound_id);
    const columnKey = measurementKey(activity);
    if (!entry.coverage.has(columnKey)) {
      entry.coverage.set(columnKey, new Set());
      entry.group.columns.push({key: columnKey, assay: activity.assay_name, metric: activity.metric, unit: activity.unit, context: activity.context, compoundCount: 0});
    }
    entry.coverage.get(columnKey)!.add(activity.compound_id);
  }
  return [...groups.values()].map(({group, compounds, coverage}) => ({
    ...group, compoundCount: compounds.size,
    columns: group.columns.map(c => ({...c, compoundCount: coverage.get(c.key)!.size}))
      .sort((a,b) => b.compoundCount - a.compoundCount || stableText(a.key, b.key)),
  })).sort((a,b) => b.compoundCount - a.compoundCount || stableText(a.key, b.key));
}

// Compare measurement availability only. Values, units and qualifiers are never
// transformed. Equal profiles stay together; natural labels make ties stable.
export function orderByMeasurementSimilarity<T extends {id: string; compound_label: string}>(
  rows: T[], cells: Map<string, Map<string, Activity[]>>, selectedColumns: string[],
): T[] {
  const columns = [...selectedColumns].sort();
  const profiles = new Map<string, {keys: Set<string>; rows: T[]}>();
  const compareRows = (a: T, b: T) => stableText(a.compound_label, b.compound_label) || stableText(a.id, b.id);
  for (const row of rows) {
    const keys = columns.filter(key => cells.get(row.id)?.get(key)?.length);
    const signature = JSON.stringify(keys);
    let profile = profiles.get(signature);
    if (!profile) { profile = {keys: new Set(keys), rows: []}; profiles.set(signature, profile); }
    profile.rows.push(row);
  }
  const pending = [...profiles.values()].filter(p => p.keys.size > 0);
  for (const profile of profiles.values()) profile.rows.sort(compareRows);
  const compareProfiles = (a: typeof pending[number], b: typeof pending[number]) =>
    b.rows.length - a.rows.length || b.keys.size - a.keys.size || compareRows(a.rows[0]!, b.rows[0]!);
  pending.sort(compareProfiles);
  const ordered: T[] = [];
  let current = pending.shift();
  while (current) {
    ordered.push(...current.rows);
    const previous = current;
    const similarity = (candidate: typeof previous) => {
      let intersection = 0;
      for (const key of candidate.keys) if (previous.keys.has(key)) intersection++;
      return intersection / (candidate.keys.size + previous.keys.size - intersection);
    };
    let best = 0;
    for (let i = 1; i < pending.length; i++) {
      const delta = similarity(pending[i]!) - similarity(pending[best]!);
      if (delta > 0 || (delta === 0 && compareProfiles(pending[i]!, pending[best]!) < 0)) best = i;
    }
    current = pending.splice(best, 1)[0];
  }
  return ordered.concat(profiles.get('[]')?.rows ?? []);
}
