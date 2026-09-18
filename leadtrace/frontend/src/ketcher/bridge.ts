import type { Ketcher } from "ketcher-core";

import {
  createChildMessage,
  parseParentMessage,
} from "../review/paper/ketcherProtocol";

interface KetcherChildWindow {
  readonly location: Pick<Location, "origin">;
  readonly parent: Pick<Window, "postMessage">;
  addEventListener(type: string, listener: EventListener): void;
  removeEventListener(type: string, listener: EventListener): void;
}

interface KetcherChildApi extends Pick<Ketcher, "setMolecule" | "getMolfile" | "changeEvent"> {}

export interface KetcherChildBridge {
  initialize(api: KetcherChildApi): void;
  dispose(): void;
  whenIdle(): Promise<void>;
}

export function createKetcherChildBridge(childWindow: KetcherChildWindow): KetcherChildBridge {
  const parentOrigin = childWindow.location.origin;
  let ketcher: KetcherChildApi | undefined;
  let disposed = false;
  let applyingParentMolecule = false;
  let moleculeSequence = 0;
  let exportSequence = 0;
  let applyQueue = Promise.resolve();

  function send(message: ReturnType<typeof createChildMessage>): void {
    if (!disposed) childWindow.parent.postMessage(message, parentOrigin);
  }

  function reportError(reason: unknown, fallback: string): void {
    const message = reason instanceof Error && reason.message ? reason.message : fallback;
    send(createChildMessage("error", message));
  }

  async function publishMolfile(expectedMoleculeSequence = moleculeSequence): Promise<void> {
    if (!ketcher || applyingParentMolecule || disposed) return;
    const sequence = ++exportSequence;
    try {
      const molfile = await ketcher.getMolfile();
      if (
        !disposed
        && sequence === exportSequence
        && expectedMoleculeSequence === moleculeSequence
      ) {
        send(createChildMessage("molfile", molfile));
      }
    } catch (reason) {
      if (sequence === exportSequence && expectedMoleculeSequence === moleculeSequence) {
        reportError(reason, "Ketcher 暂时无法导出 Molfile。");
      }
    }
  }

  function applyMolecule(molecule: string): void {
    const sequence = ++moleculeSequence;
    exportSequence += 1;
    applyQueue = applyQueue.then(async () => {
      if (!ketcher || disposed) return;
      applyingParentMolecule = true;
      try {
        await ketcher.setMolecule(molecule);
      } catch (reason) {
        if (sequence === moleculeSequence) reportError(reason, "Ketcher 无法载入当前结构文本。");
        return;
      } finally {
        applyingParentMolecule = false;
      }
      if (sequence !== moleculeSequence) return;
      await publishMolfile(sequence);
    });
  }

  const handleParentMessage: EventListener = (rawEvent) => {
    const event = rawEvent as MessageEvent;
    if (event.origin !== parentOrigin || event.source !== childWindow.parent) return;
    const message = parseParentMessage(event.data);
    if (message) applyMolecule(message.molecule);
  };

  function dispose(): void {
    if (disposed) return;
    disposed = true;
    moleculeSequence += 1;
    exportSequence += 1;
    childWindow.removeEventListener("message", handleParentMessage);
    childWindow.removeEventListener("beforeunload", handleBeforeUnload);
    ketcher?.changeEvent.remove(publishMolfile);
    ketcher = undefined;
  }

  const handleBeforeUnload: EventListener = () => dispose();
  childWindow.addEventListener("message", handleParentMessage);
  childWindow.addEventListener("beforeunload", handleBeforeUnload);

  return {
    initialize(api): void {
      if (disposed || ketcher) return;
      ketcher = api;
      ketcher.changeEvent.add(publishMolfile);
      send(createChildMessage("ready"));
    },
    dispose,
    whenIdle: () => applyQueue,
  };
}
