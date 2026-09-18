export const KETCHER_MESSAGE_PROTOCOL = "leadtrace-ketcher-v1" as const;
export const KETCHER_MESSAGE_VERSION = 1 as const;

type KetcherMessageBase = {
  protocol: typeof KETCHER_MESSAGE_PROTOCOL;
  version: typeof KETCHER_MESSAGE_VERSION;
};

export type KetcherParentMessage = KetcherMessageBase & {
  kind: "set-molecule";
  molecule: string;
};

export type KetcherChildMessage =
  | KetcherMessageBase & { kind: "ready" }
  | KetcherMessageBase & { kind: "molfile"; molfile: string }
  | KetcherMessageBase & { kind: "error"; message: string };

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

export function createSetMoleculeMessage(molecule: string): KetcherParentMessage {
  return {
    protocol: KETCHER_MESSAGE_PROTOCOL,
    version: KETCHER_MESSAGE_VERSION,
    kind: "set-molecule",
    molecule,
  };
}

export function createChildMessage(kind: "ready"): KetcherChildMessage;
export function createChildMessage(kind: "molfile", molfile: string): KetcherChildMessage;
export function createChildMessage(kind: "error", message: string): KetcherChildMessage;
export function createChildMessage(kind: KetcherChildMessage["kind"], payload?: string): KetcherChildMessage {
  const base: KetcherMessageBase = {
    protocol: KETCHER_MESSAGE_PROTOCOL,
    version: KETCHER_MESSAGE_VERSION,
  };
  if (kind === "ready") return { ...base, kind };
  if (kind === "molfile") return { ...base, kind, molfile: payload ?? "" };
  return { ...base, kind, message: payload ?? "" };
}

export function parseParentMessage(value: unknown): KetcherParentMessage | null {
  if (!isRecord(value) || !hasProtocol(value)) return null;
  if (!hasExactKeys(value, ["protocol", "version", "kind", "molecule"])) return null;
  if (value.kind !== "set-molecule" || typeof value.molecule !== "string") return null;
  return value as KetcherParentMessage;
}

export function parseChildMessage(value: unknown): KetcherChildMessage | null {
  if (!isRecord(value) || !hasProtocol(value) || typeof value.kind !== "string") return null;
  if (value.kind === "ready" && hasExactKeys(value, ["protocol", "version", "kind"])) {
    return value as KetcherChildMessage;
  }
  if (value.kind === "molfile"
    && hasExactKeys(value, ["protocol", "version", "kind", "molfile"])
    && typeof value.molfile === "string") {
    return value as KetcherChildMessage;
  }
  if (value.kind === "error"
    && hasExactKeys(value, ["protocol", "version", "kind", "message"])
    && typeof value.message === "string") {
    return value as KetcherChildMessage;
  }
  return null;
}
