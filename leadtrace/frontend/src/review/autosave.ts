import { ref, type Ref } from "vue";

import { ApiError } from "../api/client";

export type AutosaveState =
  | "idle"
  | "pending"
  | "saving"
  | "saved"
  | "offline"
  | "conflict"
  | "error";

export interface AutosaveOptions<T> {
  key: string;
  save: (value: T) => Promise<void>;
  delayMs?: number;
  storage?: Storage;
}

export interface AutosaveController<T> {
  state: Ref<AutosaveState>;
  schedule(value: T): void;
  recovery(): T | null;
  clearRecovery(): void;
  dispose(): void;
}

export class AutosaveValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AutosaveValidationError";
  }
}

function storageKey(key: string): string {
  return `leadtrace:review:autosave:${key}`;
}

export function createAutosave<T>({
  key,
  save,
  delayMs = 700,
  storage = globalThis.localStorage,
}: AutosaveOptions<T>): AutosaveController<T> {
  const state = ref<AutosaveState>("idle");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let latest: T | undefined;
  let generation = 0;
  let saving = false;
  let disposed = false;

  function clearRecovery(): void {
    storage.removeItem(storageKey(key));
  }

  function recovery(): T | null {
    const raw = storage.getItem(storageKey(key));
    if (!raw) return null;
    try {
      return JSON.parse(raw) as T;
    } catch {
      storage.removeItem(storageKey(key));
      return null;
    }
  }

  function schedule(value: T): void {
    if (disposed) return;
    latest = value;
    generation += 1;
    storage.setItem(storageKey(key), JSON.stringify(value));
    state.value = "pending";
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(flush, Math.max(0, delayMs));
  }

  async function flush(): Promise<void> {
      if (disposed || saving || latest === undefined) return;
      timer = undefined;
      const valueToSave = latest;
      const savingGeneration = generation;
      saving = true;
      state.value = "saving";
      try {
        await save(valueToSave);
        if (!disposed && savingGeneration === generation) {
          clearRecovery();
          state.value = "saved";
        } else if (!disposed) {
          state.value = "pending";
        }
      } catch (error) {
        if (!disposed && savingGeneration === generation) {
          state.value = error instanceof AutosaveValidationError
            ? "error"
            : error instanceof ApiError && error.code === "REVISION_CONFLICT"
              ? "conflict"
              : error instanceof ApiError
                ? "error"
                : "offline";
        }
      } finally {
        saving = false;
        if (!disposed && savingGeneration !== generation) {
          timer = setTimeout(flush, 0);
        }
      }
  }

  function dispose(): void {
    disposed = true;
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  }

  return { state, schedule, recovery, clearRecovery, dispose };
}
