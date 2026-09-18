export const KETCHER_MESSAGE_PROTOCOL = "leadtrace-ketcher-v1" as const;
export const KETCHER_MESSAGE_VERSION = 1 as const;

type KetcherMessageBase = {
  protocol: typeof KETCHER_MESSAGE_PROTOCOL;
  version: typeof KETCHER_MESSAGE_VERSION;
};

export type KetcherParentMessage = KetcherMessageBase & {
  kind: "set-molecule";
  requestId: number;
  molecule: string;
};

export type KetcherChildMessage =
  | KetcherMessageBase & { kind: "ready" }
  | KetcherMessageBase & { kind: "molfile"; requestId: number; molfile: string }
  | KetcherMessageBase & { kind: "error"; requestId: number | null; message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}

function hasProtocol(value: Record<string, unknown>): boolean {
  return value.protocol === KETCHER_MESSAGE_PROTOCOL && value.version === KETCHER_MESSAGE_VERSION;
}

function isRequestId(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0;
}

export function createSetMoleculeMessage(requestId: number, molecule: string): KetcherParentMessage {
  return {
    protocol: KETCHER_MESSAGE_PROTOCOL,
    version: KETCHER_MESSAGE_VERSION,
    kind: "set-molecule",
    requestId,
    molecule,
  };
}

export function createChildMessage(kind: "ready"): KetcherChildMessage;
export function createChildMessage(kind: "molfile", requestId: number, molfile: string): KetcherChildMessage;
export function createChildMessage(kind: "error", requestId: number | null, message: string): KetcherChildMessage;
export function createChildMessage(
  kind: KetcherChildMessage["kind"],
  requestId?: number | null,
  payload?: string,
): KetcherChildMessage {
  const base: KetcherMessageBase = {
    protocol: KETCHER_MESSAGE_PROTOCOL,
    version: KETCHER_MESSAGE_VERSION,
  };
  if (kind === "ready") return { ...base, kind };
  if (kind === "molfile") return { ...base, kind, requestId: requestId ?? 0, molfile: payload ?? "" };
  return { ...base, kind, requestId: requestId ?? null, message: payload ?? "" };
}

export function parseParentMessage(value: unknown): KetcherParentMessage | null {
  if (!isRecord(value) || !hasProtocol(value)) return null;
  if (!hasExactKeys(value, ["protocol", "version", "kind", "requestId", "molecule"])) return null;
  if (value.kind !== "set-molecule" || !isRequestId(value.requestId) || typeof value.molecule !== "string") return null;
  return value as KetcherParentMessage;
}

export function parseChildMessage(value: unknown): KetcherChildMessage | null {
  if (!isRecord(value) || !hasProtocol(value) || typeof value.kind !== "string") return null;
  if (value.kind === "ready" && hasExactKeys(value, ["protocol", "version", "kind"])) {
    return value as KetcherChildMessage;
  }
  if (value.kind === "molfile"
    && hasExactKeys(value, ["protocol", "version", "kind", "requestId", "molfile"])
    && isRequestId(value.requestId)
    && typeof value.molfile === "string") {
    return value as KetcherChildMessage;
  }
  if (value.kind === "error"
    && hasExactKeys(value, ["protocol", "version", "kind", "requestId", "message"])
    && (value.requestId === null || isRequestId(value.requestId))
    && typeof value.message === "string") {
    return value as KetcherChildMessage;
  }
  return null;
}
