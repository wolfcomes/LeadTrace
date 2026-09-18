import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SESSION_SYNC_STORAGE_KEY,
  createSessionSync,
} from "../src/auth/sessionSync";

type Listener = EventListenerOrEventListenerObject;

class FakeEventTarget {
  private readonly listeners = new Map<string, Set<Listener>>();

  addEventListener(type: string, listener: Listener | null): void {
    if (!listener) return;
    const listeners = this.listeners.get(type) ?? new Set<Listener>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: Listener | null): void {
    if (!listener) return;
    this.listeners.get(type)?.delete(listener);
  }

  emit(type: string, event: Event = new Event(type)): void {
    for (const listener of this.listeners.get(type) ?? []) {
      if (typeof listener === "function") listener(event);
      else listener.handleEvent(event);
    }
  }

  listenerCount(type: string): number {
    return this.listeners.get(type)?.size ?? 0;
  }
}

class FakeDocument extends FakeEventTarget {
  visibilityState: DocumentVisibilityState = "hidden";
}

class FakeStorage {
  readonly values = new Map<string, string>();
  readonly writes: Array<{ key: string; value: string }> = [];

  setItem(key: string, value: string): void {
    this.values.set(key, value);
    this.writes.push({ key, value });
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

class FakeBroadcastChannel extends FakeEventTarget {
  static instances: FakeBroadcastChannel[] = [];

  readonly sent: unknown[] = [];
  closed = false;

  constructor(readonly name: string) {
    super();
    FakeBroadcastChannel.instances.push(this);
  }

  postMessage(message: unknown): void {
    this.sent.push(message);
  }

  close(): void {
    this.closed = true;
  }

  receive(message: unknown): void {
    this.emit("message", new MessageEvent("message", { data: message }));
  }
}

class ThrowingBroadcastChannel extends FakeEventTarget {
  constructor(_name: string) {
    super();
    throw new Error("BroadcastChannel denied");
  }

  postMessage(): void {}
  close(): void {}
}

function setup(BroadcastChannel: typeof FakeBroadcastChannel | null = FakeBroadcastChannel) {
  const window = new FakeEventTarget();
  const document = new FakeDocument();
  const storage = new FakeStorage();
  const refreshSession = vi.fn().mockResolvedValue(undefined);
  const sync = createSessionSync({
    window,
    document,
    storage,
    BroadcastChannel: BroadcastChannel ?? undefined,
    refreshSession,
  });
  return { window, document, storage, refreshSession, sync };
}

describe("cross-tab session synchronization", () => {
  beforeEach(() => {
    FakeBroadcastChannel.instances = [];
  });

  it("forces a session refresh when another tab reports changed credentials", async () => {
    const { refreshSession } = setup();

    FakeBroadcastChannel.instances[0]!.receive({
      kind: "credentials-changed",
      version: 1,
    });
    await Promise.resolve();

    expect(refreshSession).toHaveBeenCalledOnce();
    expect(refreshSession).toHaveBeenCalledWith({ sessionChanged: true });
  });

  it("refreshes on focus and only when the document becomes visible", async () => {
    const { window, document, refreshSession } = setup();

    window.emit("focus");
    document.emit("visibilitychange");
    document.visibilityState = "visible";
    document.emit("visibilitychange");
    await Promise.resolve();

    expect(refreshSession).toHaveBeenCalledTimes(2);
    expect(refreshSession).toHaveBeenNthCalledWith(1);
    expect(refreshSession).toHaveBeenNthCalledWith(2);
  });

  it("publishes only a minimal versioned event kind", () => {
    const { sync } = setup();

    sync.publishCredentialsChanged();

    const signal = FakeBroadcastChannel.instances[0]!.sent[0];
    expect(signal).toEqual({ kind: "credentials-changed", version: 1 });
    expect(Object.keys(signal as object).sort()).toEqual(["kind", "version"]);
    expect(JSON.stringify(signal)).not.toMatch(/user|role|identity|session|csrf|token/i);
  });

  it("removes browser listeners and closes its channel when stopped", async () => {
    const { window, document, refreshSession, sync } = setup();
    const channel = FakeBroadcastChannel.instances[0]!;

    expect(window.listenerCount("focus")).toBe(1);
    expect(document.listenerCount("visibilitychange")).toBe(1);
    sync.stop();
    window.emit("focus");
    document.visibilityState = "visible";
    document.emit("visibilitychange");
    channel.receive({ kind: "credentials-changed", version: 1 });
    await Promise.resolve();

    expect(window.listenerCount("focus")).toBe(0);
    expect(document.listenerCount("visibilitychange")).toBe(0);
    expect(channel.closed).toBe(true);
    expect(refreshSession).not.toHaveBeenCalled();
  });

  it("receives and publishes signals through storage when BroadcastChannel is unavailable", async () => {
    const { window, storage, refreshSession, sync } = setup(null);
    const signal = { kind: "credentials-changed", version: 1 };

    window.emit("storage", {
      type: "storage",
      key: SESSION_SYNC_STORAGE_KEY,
      newValue: JSON.stringify(signal),
    } as StorageEvent);
    await Promise.resolve();
    sync.publishCredentialsChanged();

    expect(refreshSession).toHaveBeenCalledWith({ sessionChanged: true });
    expect(storage.writes).toEqual([{
      key: SESSION_SYNC_STORAGE_KEY,
      value: JSON.stringify(signal),
    }]);
  });

  it("falls back without losing focus refresh when BroadcastChannel construction throws", async () => {
    const window = new FakeEventTarget();
    const document = new FakeDocument();
    const storage = new FakeStorage();
    const refreshSession = vi.fn().mockResolvedValue(undefined);

    expect(() => createSessionSync({
      window,
      document,
      storage,
      BroadcastChannel: ThrowingBroadcastChannel,
      refreshSession,
    })).not.toThrow();

    window.emit("focus");
    await Promise.resolve();
    expect(refreshSession).toHaveBeenCalledOnce();
  });
});
