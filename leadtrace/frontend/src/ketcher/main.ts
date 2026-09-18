import type { Ketcher } from "ketcher-core";
import { Editor } from "ketcher-react";
import "ketcher-react/dist/index.css";
import { StandaloneStructServiceProvider } from "ketcher-standalone";
import { createElement } from "react";
import { createRoot } from "react-dom/client";

import { createChildMessage } from "../review/paper/ketcherProtocol";
import { createKetcherChildBridge } from "./bridge";
import "./styles.css";

const host = document.querySelector<HTMLDivElement>("#ketcher-root");
if (!host) throw new Error("Ketcher root element is missing");

const root = createRoot(host);
const bridge = createKetcherChildBridge(window);

function reportError(reason: unknown, fallback: string): void {
  const message = reason instanceof Error && reason.message ? reason.message : fallback;
  window.parent.postMessage(createChildMessage("error", message), window.location.origin);
}

function initialize(api: Ketcher): void {
  bridge.initialize(api);
}

function cleanup(): void {
  window.removeEventListener("beforeunload", cleanup);
  bridge.dispose();
  root.unmount();
}

window.addEventListener("beforeunload", cleanup);

try {
  root.render(createElement(Editor, {
    staticResourcesUrl: "",
    structServiceProvider: new StandaloneStructServiceProvider(),
    errorHandler: (message: string) => window.parent.postMessage(
      createChildMessage("error", message || "Ketcher 编辑器发生错误。"),
      window.location.origin,
    ),
    onInit: initialize,
    disableMacromoleculesEditor: true,
  }));
} catch (reason) {
  reportError(reason, "Ketcher 编辑器未能载入，请重试。");
}
