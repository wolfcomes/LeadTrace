import type { Ketcher } from "ketcher-core";
import { Editor } from "ketcher-react";
import "ketcher-react/dist/index.css";
import { StandaloneStructServiceProvider } from "ketcher-standalone";
import { createElement } from "react";
import { createRoot } from "react-dom/client";

import {
  createChildMessage,
  parseParentMessage,
} from "../review/paper/ketcherProtocol";
import "./styles.css";

const host = document.querySelector<HTMLDivElement>("#ketcher-root");
if (!host) throw new Error("Ketcher root element is missing");

const parentOrigin = window.location.origin;
const root = createRoot(host);
let ketcher: Ketcher | undefined;
let applyingParentMolecule = false;
let applySequence = 0;
let exportSequence = 0;
let applyQueue = Promise.resolve();

function send(message: ReturnType<typeof createChildMessage>): void {
  window.parent.postMessage(message, parentOrigin);
}

function reportError(reason: unknown, fallback: string): void {
  const message = reason instanceof Error && reason.message ? reason.message : fallback;
  send(createChildMessage("error", message));
}

async function publishMolfile(): Promise<void> {
  if (!ketcher || applyingParentMolecule) return;
  const sequence = ++exportSequence;
  try {
    const molfile = await ketcher.getMolfile();
    if (sequence === exportSequence) send(createChildMessage("molfile", molfile));
  } catch (reason) {
    reportError(reason, "Ketcher 暂时无法导出 Molfile。");
  }
}

function applyMolecule(molecule: string): void {
  const sequence = ++applySequence;
  applyQueue = applyQueue.then(async () => {
    if (!ketcher || sequence !== applySequence) return;
    applyingParentMolecule = true;
    try {
      await ketcher.setMolecule(molecule);
    } catch (reason) {
      reportError(reason, "Ketcher 无法载入当前结构文本。");
      return;
    } finally {
      applyingParentMolecule = false;
    }
    await publishMolfile();
  });
}

function handleParentMessage(event: MessageEvent): void {
  if (event.origin !== parentOrigin || event.source !== window.parent) return;
  const message = parseParentMessage(event.data);
  if (message) applyMolecule(message.molecule);
}

function initialize(api: Ketcher): void {
  ketcher = api;
  ketcher.changeEvent.add(publishMolfile);
  send(createChildMessage("ready"));
}

function cleanup(): void {
  window.removeEventListener("message", handleParentMessage);
  window.removeEventListener("beforeunload", cleanup);
  ketcher?.changeEvent.remove(publishMolfile);
  ketcher = undefined;
  root.unmount();
}

window.addEventListener("message", handleParentMessage);
window.addEventListener("beforeunload", cleanup);

try {
  root.render(createElement(Editor, {
    staticResourcesUrl: "",
    structServiceProvider: new StandaloneStructServiceProvider(),
    errorHandler: (message: string) => send(createChildMessage("error", message || "Ketcher 编辑器发生错误。")),
    onInit: initialize,
    disableMacromoleculesEditor: true,
  }));
} catch (reason) {
  reportError(reason, "Ketcher 编辑器未能载入，请重试。");
}
