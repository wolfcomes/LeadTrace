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
