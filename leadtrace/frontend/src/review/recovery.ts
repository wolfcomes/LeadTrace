export interface WorkspaceValues {
  title: string;
  reason: string;
  itemJson: Record<string, string>;
}

export interface WorkspaceRecovery extends WorkspaceValues {
  baseVersion: number;
  base?: WorkspaceValues;
}

export type RecoveryResolution = "local" | "server";

export interface RecoveryConflict {
  key: string;
  label: string;
  path: string;
  localValue: unknown;
  serverValue: unknown;
  localPresent: boolean;
  serverPresent: boolean;
}

export interface RecoveryMergeResult {
  values: WorkspaceValues;
  conflicts: RecoveryConflict[];
  complete: boolean;
}

const missing = Symbol("missing");
type MergeValue = unknown | typeof missing;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && !Array.isArray(value) && typeof value === "object";
}

function sameValue(left: MergeValue, right: MergeValue): boolean {
  if (left === missing || right === missing) return left === right;
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) && Array.isArray(right)) {
    return left.length === right.length
      && left.every((entry, index) => sameValue(entry, right[index]));
  }
  if (isRecord(left) && isRecord(right)) {
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return leftKeys.length === rightKeys.length
      && leftKeys.every((key, index) => (
        key === rightKeys[index] && sameValue(left[key], right[key])
      ));
  }
  return false;
}

function pointerSegment(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function visibleValue(value: MergeValue): unknown {
  return value === missing ? null : value;
}

function mergeValue(
  base: MergeValue,
  local: MergeValue,
  server: MergeValue,
  label: string,
  path: string,
  keyPrefix: string,
  resolutions: Record<string, RecoveryResolution>,
  conflicts: RecoveryConflict[],
): MergeValue {
  if (sameValue(local, base)) return server;
  if (sameValue(server, base) || sameValue(local, server)) return local;

  if (isRecord(base) && isRecord(local) && isRecord(server)) {
    const merged: Record<string, unknown> = {};
    const keys = new Set([
      ...Object.keys(base),
      ...Object.keys(local),
      ...Object.keys(server),
    ]);
    for (const key of [...keys].sort()) {
      const childPath = `${path}/${pointerSegment(key)}`;
      const child = mergeValue(
        key in base ? base[key] : missing,
        key in local ? local[key] : missing,
        key in server ? server[key] : missing,
        label,
        childPath,
        keyPrefix,
        resolutions,
        conflicts,
      );
      if (child !== missing) merged[key] = child;
    }
    return merged;
  }

  const key = `${keyPrefix}:${path || "/"}`;
  conflicts.push({
    key,
    label,
    path: path || "/",
    localValue: visibleValue(local),
    serverValue: visibleValue(server),
    localPresent: local !== missing,
    serverPresent: server !== missing,
  });
  return resolutions[key] === "local" ? local : server;
}

function parseSnapshot(raw: MergeValue): MergeValue {
  if (raw === missing) return missing;
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

function serializeSnapshot(value: MergeValue): string | undefined {
  if (value === missing) return undefined;
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

export function mergeWorkspaceRecovery(
  recovery: WorkspaceRecovery,
  server: WorkspaceValues,
  resolutions: Record<string, RecoveryResolution> = {},
): RecoveryMergeResult {
  const conflicts: RecoveryConflict[] = [];
  const base = recovery.base;
  const mergeScalar = (
    field: "title" | "reason",
    label: string,
  ): string => {
    const baseValue = base ? base[field] : missing;
    const merged = mergeValue(
      baseValue,
      recovery[field],
      server[field],
      label,
      `/${field}`,
      field,
      resolutions,
      conflicts,
    );
    return typeof merged === "string" ? merged : server[field];
  };

  const itemJson: Record<string, string> = {};
  const itemIds = new Set([
    ...Object.keys(base?.itemJson ?? {}),
    ...Object.keys(recovery.itemJson ?? {}),
    ...Object.keys(server.itemJson),
  ]);
  for (const itemId of [...itemIds].sort()) {
    const baseRaw = base && itemId in base.itemJson ? base.itemJson[itemId] : missing;
    const localRaw = itemId in recovery.itemJson ? recovery.itemJson[itemId] : missing;
    const serverRaw = itemId in server.itemJson ? server.itemJson[itemId] : missing;
    const canMergeJson = base !== undefined
      && [baseRaw, localRaw, serverRaw].every((value) => (
        value === missing || (typeof value === "string" && isRecord(parseSnapshot(value)))
      ));
    const merged = mergeValue(
      canMergeJson ? parseSnapshot(baseRaw) : baseRaw,
      canMergeJson ? parseSnapshot(localRaw) : localRaw,
      canMergeJson ? parseSnapshot(serverRaw) : serverRaw,
      `对象 ${itemId}`,
      canMergeJson ? "" : "/snapshot",
      `item:${itemId}`,
      resolutions,
      conflicts,
    );
    const serialized = serializeSnapshot(merged);
    if (serialized !== undefined) itemJson[itemId] = serialized;
  }

  return {
    values: {
      title: mergeScalar("title", "修改集标题"),
      reason: mergeScalar("reason", "修改原因"),
      itemJson,
    },
    conflicts,
    complete: conflicts.every((entry) => resolutions[entry.key] !== undefined),
  };
}
