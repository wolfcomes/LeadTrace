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
      molecule: "CCO",
    }, window.location.origin);
    expect(wrapper.find(".ketcher-loading").exists()).toBe(false);
  });

  it("emits child Molfile output without sending the echoed parent value back", async () => {
    const wrapper = mountEditor({ modelValue: "CCO" });
    const iframe = wrapper.get("iframe").element as HTMLIFrameElement;
    const postMessage = vi.spyOn(iframe.contentWindow!, "postMessage");

    dispatchChildMessage(iframe, createChildMessage("ready"));
    dispatchChildMessage(iframe, createChildMessage("molfile", "MOCK MOLFILE"));
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
    dispatchChildMessage(iframe, createChildMessage("error", "Ketcher failed"));
    await flushPromises();

    expect(wrapper.emitted("error")).toEqual([["Ketcher failed"]]);
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
});
