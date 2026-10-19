import { z } from 'zod';
import type { Activity, Compound } from '../../v2/types';
import { measurementGroups, orderByMeasurementSimilarity } from './activityComparison';

export const columnSchema = z.object({
  id: z.string().min(1).max(128), label: z.string().trim().min(1).max(512),
  assay: z.string().min(1).max(2000), metric: z.string().min(1).max(500), unit: z.string().max(500).nullable(),
  activityIds: z.array(z.string().min(1).max(100)).max(10000).nullable(),
}).strict();
export const tableSchema = z.object({
  id: z.string().min(1).max(100), name: z.string().trim().min(1).max(512),
  columns: z.array(columnSchema).max(200).refine(cols => new Set(cols.map(c => c.id)).size === cols.length),
  mode: z.enum(['any','all']), sort: z.enum(['label','similarity','default']),
}).strict();
const savedSchema = z.object({version:z.literal(1), activeId:z.string().nullable(), tables:z.array(tableSchema).max(50)})
  .strict().refine(s => new Set(s.tables.map(t => t.id)).size === s.tables.length && (s.activeId === null || s.tables.some(t => t.id === s.activeId)));
export type ComparisonColumn = z.infer<typeof columnSchema>;
export type ComparisonTable = z.infer<typeof tableSchema>;
export type SavedTables = z.infer<typeof savedSchema>;
export function tableStorageKey(username: string, workspaceId: string): string {
  return `leadtrace.activity-tables.v1:${JSON.stringify([username,workspaceId])}`;
}
export function parseSavedTables(raw: string | null): SavedTables | null {
  if (!raw) return null;
  try { const parsed = savedSchema.safeParse(JSON.parse(raw)); return parsed.success ? parsed.data : null; }
  catch { return null; }
}
export function matchingActivities(column: ComparisonColumn, activities: Activity[]): Activity[] {
  const ids = column.activityIds === null ? null : new Set(column.activityIds);
  return activities.filter(a => a.assay_name === column.assay && a.metric === column.metric && a.unit === column.unit && (ids === null || ids.has(a.id)));
}
export function buildComparisonTable(compounds: Compound[], activities: Activity[], columns: ComparisonColumn[], mode: ComparisonTable['mode'], sort: ComparisonTable['sort'], compoundIds?: string[] | null) {
  const cells = new Map<string, Map<string, Activity[]>>();
  const matches = new Map(columns.map(column => [column.id, matchingActivities(column,activities)]));
  for (const column of columns) for (const activity of matches.get(column.id)!) {
    let row = cells.get(activity.compound_id);
    if (!row) { row = new Map(); cells.set(activity.compound_id,row); }
    const observations = row.get(column.id) ?? [];
    observations.push(activity); row.set(column.id,observations);
  }
  const byId = new Map(compounds.map(c=>[c.id,c]));
  let rows = compoundIds != null ? compoundIds.flatMap(id=>byId.has(id)?[byId.get(id)!]:[]) : compounds.filter(c => columns.length && (mode === 'all' ? columns.every(col => cells.get(c.id)?.get(col.id)?.length) : cells.has(c.id)));
  if (sort === 'label') {
    const collator = new Intl.Collator('en',{numeric:true,sensitivity:'base'});
    rows.sort((a,b) => collator.compare(a.compound_label,b.compound_label) || a.id.localeCompare(b.id));
  } else if (sort === 'similarity') rows = orderByMeasurementSimilarity(rows,cells,columns.map(c => c.id));
  return {rows,cells,matches};
}
export function recommendMeasurements(activities: Activity[], columns: ComparisonColumn[]) {
  const selected = new Set(columns.flatMap(c => matchingActivities(c,activities).map(a => a.compound_id)));
  return measurementGroups(activities).map(group => {
    const coverage = new Set(matchingActivities({id:'candidate',label:'candidate',assay:group.assay,metric:group.metric,unit:group.unit,activityIds:null},activities).map(a => a.compound_id));
    const sharedCompounds = [...coverage].filter(id => selected.has(id)).length;
    const similarity = selected.size ? sharedCompounds / (selected.size + coverage.size - sharedCompounds) : 0;
    return {...group,sharedCompounds,similarity};
  }).sort((a,b) => b.similarity - a.similarity || b.compoundCount - a.compoundCount || a.key.localeCompare(b.key));
}

// Layout suggestions compare availability, never measurement values or condition semantics.
// Exact coverage profiles are kept together before complete-link similarity merging.
export function suggestTableColumns(activities: Activity[]): ComparisonColumn[][] {
  const groups = new Map<string, {column: ComparisonColumn; coverage: Set<string>}>();
  for (const a of activities) {
    const key = JSON.stringify([a.assay_name,a.metric,a.unit]);
    let group = groups.get(key);
    if (!group) {
      group = {column: {id:crypto.randomUUID(),label:`${a.assay_name} · ${a.metric}`.slice(0,160),assay:a.assay_name,metric:a.metric,unit:a.unit,activityIds:null},coverage:new Set()};
      groups.set(key,group);
    }
    group.coverage.add(a.compound_id);
  }
  const collator = new Intl.Collator('en',{numeric:true,sensitivity:'base'});
  const compareText = (a:string,b:string) => collator.compare(a,b) || (a<b?-1:a>b?1:0);
  const ordered = [...groups.entries()].sort(([ka,a],[kb,b])=>b.coverage.size-a.coverage.size || compareText(ka,kb));
  const profiles = new Map<string, typeof ordered>();
  for (const entry of ordered) {
    const signature = JSON.stringify([...entry[1].coverage].sort());
    const profile = profiles.get(signature) ?? [];profile.push(entry);profiles.set(signature,profile);
  }
  const similarity = (a:Set<string>,b:Set<string>) => {
    let shared=0;for (const id of a) if (b.has(id)) shared++;
    return shared/(a.size+b.size-shared);
  };
  const clusters: Array<Array<typeof ordered>> = [];
  for (const profile of profiles.values()) {
    let best: typeof clusters[number] | undefined, score = -1;
    for (const cluster of clusters) {
      const minimum = Math.min(...cluster.map(other=>similarity(profile[0]![1].coverage,other[0]![1].coverage)));
      if (minimum >= 0.8 && minimum > score) {best=cluster;score=minimum;}
    }
    if (best) best.push(profile);else clusters.push([profile]);
  }
  const result: ComparisonColumn[][] = [];
  for (const cluster of clusters) {
    const columns=cluster.flat().map(([,group])=>group.column);
    for (let index=0;index<columns.length;index+=6) result.push(columns.slice(index,index+6));
  }
  return result;
}
