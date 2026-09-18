import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { createKetcherChildBridge } from "../src/ketcher/bridge";
import {
  createSetMoleculeMessage,
  KETCHER_MESSAGE_PROTOCOL,
  KETCHER_MESSAGE_VERSION,
} from "../src/review/paper/ketcherProtocol";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => {
    resolve = finish;
  });
  return { promise, resolve };
}

function createHarness() {
  const listeners = new Map<string, EventListener>();
  const parent = { postMessage: vi.fn() };
  const childWindow = {
    location: { origin: "https://leadtrace.test" },
    parent,
    addEventListener: vi.fn((type: string, listener: EventListener) => {
      listeners.set(type, listener);
    }),
    removeEventListener: vi.fn((type: string, listener: EventListener) => {
      if (listeners.get(type) === listener) listeners.delete(type);
    }),
  };
  const changeEvent = { add: vi.fn(), remove: vi.fn() };
  const api = {
    changeEvent,
    setMolecule: vi.fn<(molecule: string) => Promise<void>>(async () => undefined),
    getMolfile: vi.fn(async () => "MOLFILE"),
  };

  return {
    api,
    changeEvent,
    childWindow,
    listeners,
    parent,
    dispatch(data: unknown, options: { origin?: string; source?: unknown } = {}) {
      listeners.get("message")?.({
        data,
        origin: options.origin ?? childWindow.location.origin,
        source: options.source ?? parent,
      } as unknown as Event);
    },
  };
}

describe("Ketcher child bridge", () => {
  it("announces readiness only after API initialization and accepts only its same-origin parent", async () => {
    const harness = createHarness();
    const bridge = createKetcherChildBridge(harness.childWindow);

    expect(harness.parent.postMessage).not.toHaveBeenCalled();
    bridge.initialize(harness.api);
    expect(harness.parent.postMessage).toHaveBeenCalledWith({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "ready",
    }, harness.childWindow.location.origin);

    harness.dispatch(createSetMoleculeMessage(1, "ATTACKER"), { origin: "https://attacker.example" });
    harness.dispatch(createSetMoleculeMessage(1, "WRONG SOURCE"), { source: {} });
    harness.dispatch({ protocol: KETCHER_MESSAGE_PROTOCOL, version: 99, kind: "set-molecule", molecule: "BAD" });
    await Promise.resolve();
    expect(harness.api.setMolecule).not.toHaveBeenCalled();

    harness.dispatch(createSetMoleculeMessage(1, "CCO"));
    await bridge.whenIdle();
    expect(harness.api.setMolecule).toHaveBeenCalledWith("CCO");
  });

  it("serializes parent updates without publishing an older molecule after a newer input arrives", async () => {
    const harness = createHarness();
    const firstImport = deferred<void>();
    harness.api.setMolecule
      .mockImplementationOnce(() => firstImport.promise)
      .mockResolvedValueOnce(undefined);
    harness.api.getMolfile.mockResolvedValue("LATEST MOLFILE");
    const bridge = createKetcherChildBridge(harness.childWindow);
    bridge.initialize(harness.api);
    harness.parent.postMessage.mockClear();

    harness.dispatch(createSetMoleculeMessage(1, "A"));
    await Promise.resolve();
    harness.dispatch(createSetMoleculeMessage(2, "B"));
    firstImport.resolve();
    await bridge.whenIdle();

    expect(harness.api.setMolecule.mock.calls).toEqual([["A"], ["B"]]);
    expect(harness.api.getMolfile).toHaveBeenCalledOnce();
    expect(harness.parent.postMessage).toHaveBeenCalledTimes(1);
    expect(harness.parent.postMessage).toHaveBeenCalledWith({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "molfile",
      requestId: 2,
      molfile: "LATEST MOLFILE",
    }, harness.childWindow.location.origin);
  });

  it("publishes export errors and removes all listeners on unload", async () => {
    const harness = createHarness();
    harness.api.getMolfile.mockRejectedValue(new Error("export failed"));
    const bridge = createKetcherChildBridge(harness.childWindow);
    bridge.initialize(harness.api);
    harness.parent.postMessage.mockClear();

    const changeHandler = harness.changeEvent.add.mock.calls[0]?.[0] as () => Promise<void>;
    await changeHandler();
    expect(harness.parent.postMessage).toHaveBeenCalledWith({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "error",
      requestId: null,
      message: "export failed",
    }, harness.childWindow.location.origin);

    listenersCall(harness.listeners, "beforeunload");
    expect(harness.changeEvent.remove).toHaveBeenCalledWith(changeHandler);
    expect(harness.childWindow.removeEventListener).toHaveBeenCalledWith("message", expect.any(Function));
    expect(harness.childWindow.removeEventListener).toHaveBeenCalledWith("beforeunload", expect.any(Function));
  });

  it("publishes user edits even when Ketcher supplies a change-event payload", async () => {
    const harness = createHarness();
    const bridge = createKetcherChildBridge(harness.childWindow);
    bridge.initialize(harness.api);
    harness.parent.postMessage.mockClear();

    harness.dispatch(createSetMoleculeMessage(1, "CCO"));
    await bridge.whenIdle();
    harness.parent.postMessage.mockClear();
    const changeHandler = harness.changeEvent.add.mock.calls[0]?.[0] as (event: unknown) => Promise<void>;
    await changeHandler({ source: "canvas" });

    expect(harness.parent.postMessage).toHaveBeenCalledWith({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "molfile",
      requestId: 1,
      molfile: "MOLFILE",
    }, harness.childWindow.location.origin);
  });

  it("publishes an import error for the latest parent molecule", async () => {
    const harness = createHarness();
    harness.api.setMolecule.mockRejectedValue(new Error("import failed"));
    const bridge = createKetcherChildBridge(harness.childWindow);
    bridge.initialize(harness.api);
    harness.parent.postMessage.mockClear();

    harness.dispatch(createSetMoleculeMessage(1, "INVALID"));
    await bridge.whenIdle();

    expect(harness.parent.postMessage).toHaveBeenCalledWith({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "error",
      requestId: 1,
      message: "import failed",
    }, harness.childWindow.location.origin);
  });

  it("keeps the failure message inside the fixed-height editor island", () => {
    const css = readFileSync(resolve(import.meta.dirname, "../src/styles/components.css"), "utf8");

    expect(css).toContain(".ketcher-island { position: relative; min-height: 480px; height: 480px;");
    expect(css).toContain(".ketcher-failed { position: absolute;");
  });
});

function listenersCall(listeners: Map<string, EventListener>, type: string): void {
  listeners.get(type)?.(new Event(type));
}
