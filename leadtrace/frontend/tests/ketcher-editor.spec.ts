import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import KetcherEditor from "../src/review/paper/KetcherEditor.vue";
import {
  KETCHER_MESSAGE_PROTOCOL,
  KETCHER_MESSAGE_VERSION,
  createChildMessage,
} from "../src/review/paper/ketcherProtocol";

function dispatchChildMessage(
  iframe: HTMLIFrameElement,
  data: unknown,
  options: { origin?: string; source?: MessageEventSource | null } = {},
): void {
  window.dispatchEvent(new MessageEvent("message", {
    data,
    origin: options.origin ?? window.location.origin,
    source: options.source ?? iframe.contentWindow,
  }));
}

describe("Ketcher iframe adapter", () => {
  const wrappers: VueWrapper[] = [];

  function mountEditor(props: { modelValue?: string | null; disabled?: boolean } = {}): VueWrapper {
    const wrapper = mount(KetcherEditor, { attachTo: document.body, props });
    wrappers.push(wrapper);
    return wrapper;
  }

  afterEach(() => {
    for (const wrapper of wrappers.splice(0)) wrapper.unmount();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("mounts only while editing is available and removes its message listener", async () => {
    const addListener = vi.spyOn(window, "addEventListener");
    const removeListener = vi.spyOn(window, "removeEventListener");
    const wrapper = mountEditor({ modelValue: "CCO", disabled: true });

    expect(wrapper.find("iframe").exists()).toBe(false);
    expect(addListener).not.toHaveBeenCalledWith("message", expect.any(Function));

    await wrapper.setProps({ disabled: false });
    expect(wrapper.get("iframe").attributes("src")).toBe("/ketcher.html");
    expect(addListener).toHaveBeenCalledWith("message", expect.any(Function));

    await wrapper.setProps({ disabled: true });
    expect(wrapper.find("iframe").exists()).toBe(false);
    expect(removeListener).toHaveBeenCalledWith("message", expect.any(Function));

  });

  it("rejects exposed requests immediately while editing is disabled", async () => {
    const wrapper = mountEditor({ modelValue: "CCO", disabled: true });
    const editor = wrapper.vm as unknown as {
      setMolecule(value: string): Promise<void>;
      getMolfile(): Promise<string>;
    };

    await expect(editor.setMolecule("CCC")).rejects.toThrow("停用");
    await expect(editor.getMolfile()).rejects.toThrow("停用");
  });

  it("restores the current molecule request after editing is disabled and re-enabled", async () => {
    const wrapper = mountEditor({ modelValue: "CCO" });
    const firstIframe = wrapper.get("iframe").element as HTMLIFrameElement;
    dispatchChildMessage(firstIframe, createChildMessage("ready"));

    await wrapper.setProps({ disabled: true });
    await wrapper.setProps({ disabled: false });
    const secondIframe = wrapper.get("iframe").element as HTMLIFrameElement;
    const postMessage = vi.spyOn(secondIframe.contentWindow!, "postMessage");
    dispatchChildMessage(secondIframe, createChildMessage("ready"));
    await flushPromises();

    expect(postMessage).toHaveBeenCalledWith({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "set-molecule",
      requestId: 2,
      molecule: "CCO",
    }, window.location.origin);
  });

  it("accepts ready only from its same-origin child and then sends the initial SMILES", async () => {
    const wrapper = mountEditor({ modelValue: "CCO" });
    const iframe = wrapper.get("iframe").element as HTMLIFrameElement;
    const postMessage = vi.spyOn(iframe.contentWindow!, "postMessage");
    const ready = createChildMessage("ready");

    dispatchChildMessage(iframe, ready, { origin: "https://attacker.example" });
    dispatchChildMessage(iframe, ready, { source: window });
    expect(postMessage).not.toHaveBeenCalled();

    dispatchChildMessage(iframe, ready);
    await flushPromises();

    expect(postMessage).toHaveBeenCalledWith({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "set-molecule",
      requestId: 1,
      molecule: "CCO",
    }, window.location.origin);
    expect(wrapper.find(".ketcher-loading").exists()).toBe(false);
  });

  it("emits child Molfile output without sending the echoed parent value back", async () => {
    const wrapper = mountEditor({ modelValue: "CCO" });
    const iframe = wrapper.get("iframe").element as HTMLIFrameElement;
    const postMessage = vi.spyOn(iframe.contentWindow!, "postMessage");

    dispatchChildMessage(iframe, createChildMessage("ready"));
    dispatchChildMessage(iframe, createChildMessage("molfile", 1, "MOCK MOLFILE"));
    await flushPromises();

    expect(wrapper.emitted("update:modelValue")).toEqual([["MOCK MOLFILE"]]);
    expect(postMessage).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ modelValue: "MOCK MOLFILE" });
    await flushPromises();
    expect(postMessage).toHaveBeenCalledTimes(1);
  });

  it("reports child errors and ignores malformed child messages", async () => {
    const wrapper = mountEditor();
    const iframe = wrapper.get("iframe").element as HTMLIFrameElement;

    dispatchChildMessage(iframe, { protocol: KETCHER_MESSAGE_PROTOCOL, version: 99, kind: "error", message: "bad" });
    dispatchChildMessage(iframe, createChildMessage("error", null, "Ketcher failed"));
    await flushPromises();

    expect(wrapper.emitted("error")).toEqual([["Ketcher failed"]]);
  });

  it("ignores a Molfile response from the molecule request superseded by the parent", async () => {
    const wrapper = mountEditor({ modelValue: "A" });
    const iframe = wrapper.get("iframe").element as HTMLIFrameElement;

    dispatchChildMessage(iframe, createChildMessage("ready"));
    await wrapper.setProps({ modelValue: "B" });
    dispatchChildMessage(iframe, createChildMessage("molfile", 1, "STALE A MOLFILE"));
    dispatchChildMessage(iframe, createChildMessage("molfile", 2, "CURRENT B MOLFILE"));
    await flushPromises();

    expect(wrapper.emitted("update:modelValue")).toEqual([["CURRENT B MOLFILE"]]);
  });

  it("waits for the correlated child output in its exposed set/get methods", async () => {
    const wrapper = mountEditor();
    const iframe = wrapper.get("iframe").element as HTMLIFrameElement;
    dispatchChildMessage(iframe, createChildMessage("ready"));

    let settled = false;
    const setting = (wrapper.vm as unknown as {
      setMolecule(value: string): Promise<void>;
      getMolfile(): Promise<string>;
    }).setMolecule("CCO").then(() => { settled = true; });
    await flushPromises();
    expect(settled).toBe(false);

    dispatchChildMessage(iframe, createChildMessage("molfile", 2, "ETHANOL MOLFILE"));
    await setting;
    await expect((wrapper.vm as unknown as {
      getMolfile(): Promise<string>;
    }).getMolfile()).resolves.toBe("ETHANOL MOLFILE");
  });

  it("reports an unresponsive child after a bounded initialization timeout", async () => {
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const wrapper = mountEditor();
    await flushPromises();

    const timeoutCall = setTimeoutSpy.mock.calls.find(([, delay]) => delay === 15_000);
    expect(timeoutCall).toBeDefined();
    (timeoutCall![0] as () => void)();
    await wrapper.vm.$nextTick();

    expect(wrapper.emitted("error")).toEqual([["Ketcher 编辑器未能载入，请重试。"]]);
    expect(wrapper.find(".ketcher-loading").exists()).toBe(false);
  });

  it("rejects an exposed molecule request when initialization times out", async () => {
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const wrapper = mountEditor();
    await flushPromises();

    const setting = (wrapper.vm as unknown as {
      setMolecule(value: string): Promise<void>;
    }).setMolecule("CCO");
    const timeoutCall = setTimeoutSpy.mock.calls.find(([, delay]) => delay === 15_000);
    (timeoutCall![0] as () => void)();

    await expect(setting).rejects.toThrow("未能载入");
  });

  it("resynchronizes the current molecule when readiness arrives after the timeout", async () => {
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const wrapper = mountEditor({ modelValue: "CCO" });
    await flushPromises();
    const iframe = wrapper.get("iframe").element as HTMLIFrameElement;
    const postMessage = vi.spyOn(iframe.contentWindow!, "postMessage");
    const timeoutCall = setTimeoutSpy.mock.calls.find(([, delay]) => delay === 15_000);
    (timeoutCall![0] as () => void)();

    dispatchChildMessage(iframe, createChildMessage("ready"));
    await flushPromises();

    expect(postMessage).toHaveBeenCalledWith({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "set-molecule",
      requestId: 2,
      molecule: "CCO",
    }, window.location.origin);
    expect(postMessage).toHaveBeenCalledTimes(1);
  });
});
