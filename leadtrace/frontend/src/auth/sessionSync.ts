export const SESSION_SYNC_STORAGE_KEY = "leadtrace:session-sync";

const SESSION_SYNC_CHANNEL = "leadtrace-session";
const CREDENTIALS_CHANGED_SIGNAL = Object.freeze({
  kind: "credentials-changed",
  version: 1,
} as const);

export interface SessionRefreshOptions {
  sessionChanged?: boolean;
}

interface SessionSyncEventTarget {
  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
}

interface SessionSyncDocument extends SessionSyncEventTarget {
  readonly visibilityState: DocumentVisibilityState;
}

interface SessionSyncStorage {
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

interface SessionSyncChannel extends SessionSyncEventTarget {
  postMessage(message: unknown): void;
  close(): void;
}

interface SessionSyncDependencies {
  window: SessionSyncEventTarget;
  document: SessionSyncDocument;
  storage?: SessionSyncStorage;
  BroadcastChannel?: new (name: string) => SessionSyncChannel;
  refreshSession(options?: SessionRefreshOptions): Promise<void>;
}

export interface SessionSync {
  publishCredentialsChanged(): void;
  stop(): void;
}

function isCredentialsChangedSignal(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const signal = value as Record<string, unknown>;
  return Object.keys(signal).length === 2
    && signal.kind === CREDENTIALS_CHANGED_SIGNAL.kind
    && signal.version === CREDENTIALS_CHANGED_SIGNAL.version;
}

export function createSessionSync(dependencies: SessionSyncDependencies): SessionSync {
  const {
    window,
    document,
    storage,
    BroadcastChannel,
    refreshSession,
  } = dependencies;
  let channel: SessionSyncChannel | undefined;
  if (BroadcastChannel) {
    try {
      channel = new BroadcastChannel(SESSION_SYNC_CHANNEL);
    } catch {
      channel = undefined;
    }
  }
  let stopped = false;

  function requestRefresh(options?: SessionRefreshOptions): void {
    void Promise.resolve()
      .then(() => options ? refreshSession(options) : refreshSession())
      .catch(() => undefined);
  }

  const handleFocus: EventListener = () => requestRefresh();
  const handleVisibilityChange: EventListener = () => {
    if (document.visibilityState === "visible") requestRefresh();
  };
  const handleMessage: EventListener = (event) => {
    if (isCredentialsChangedSignal((event as MessageEvent).data)) {
      requestRefresh({ sessionChanged: true });
    }
  };
  const handleStorage: EventListener = (event) => {
    const storageEvent = event as StorageEvent;
    if (storageEvent.key !== SESSION_SYNC_STORAGE_KEY || !storageEvent.newValue) return;
    try {
      if (isCredentialsChangedSignal(JSON.parse(storageEvent.newValue))) {
        requestRefresh({ sessionChanged: true });
      }
    } catch {
      // Ignore malformed values written by unrelated code.
    }
  };

  window.addEventListener("focus", handleFocus);
  document.addEventListener("visibilitychange", handleVisibilityChange);
  if (channel) channel.addEventListener("message", handleMessage);
  else window.addEventListener("storage", handleStorage);

  return {
    publishCredentialsChanged(): void {
      if (stopped) return;
      if (channel) {
        channel.postMessage(CREDENTIALS_CHANGED_SIGNAL);
        return;
      }
      if (!storage) return;
      try {
        storage.removeItem(SESSION_SYNC_STORAGE_KEY);
        storage.setItem(
          SESSION_SYNC_STORAGE_KEY,
          JSON.stringify(CREDENTIALS_CHANGED_SIGNAL),
        );
        storage.removeItem(SESSION_SYNC_STORAGE_KEY);
      } catch {
        // Storage can be disabled while focus-based synchronization still works.
      }
    },
    stop(): void {
      if (stopped) return;
      stopped = true;
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      if (channel) {
        channel.removeEventListener("message", handleMessage);
        channel.close();
      } else {
        window.removeEventListener("storage", handleStorage);
      }
    },
  };
}
