import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import KetcherEditor from "../src/review/paper/KetcherEditor.vue";


const mocks = vi.hoisted(() => {
  const changeEvent = { add: vi.fn(), remove: vi.fn() };
  const api = {
    changeEvent,
    setMolecule: vi.fn(async () => undefined),
    getMolfile: vi.fn(async () => "MOCK MOLFILE"),
  };
  const root = { render: vi.fn(), unmount: vi.fn() };
  const createRoot = vi.fn(() => root);
  const createElement = vi.fn((_type: unknown, props: Record<string, unknown>) => ({ props }));
  root.render.mockImplementation((element: { props: { onInit?: (value: typeof api) => void } }) => {
    element.props.onInit?.(api);
  });
  return { api, changeEvent, root, createRoot, createElement };
});

vi.mock("react", () => ({ createElement: mocks.createElement }));
vi.mock("react-dom/client", () => ({ createRoot: mocks.createRoot }));
vi.mock("ketcher-react", () => ({ Editor: Symbol("Editor") }));
vi.mock("ketcher-standalone", () => ({ StandaloneStructServiceProvider: class {} }));
vi.mock("ketcher-react/dist/index.css", () => ({}));

describe("Ketcher Vue island", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("mounts when editing becomes available and tears down when it becomes read-only", async () => {
    const wrapper = mount(KetcherEditor, { props: { modelValue: "CCO", disabled: true } });
    await flushPromises();
    expect(mocks.createRoot).not.toHaveBeenCalled();

    await wrapper.setProps({ disabled: false });
    await flushPromises();
    expect(mocks.createRoot).toHaveBeenCalledTimes(1);
    expect(mocks.changeEvent.add).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ disabled: true });
    await flushPromises();
    expect(mocks.changeEvent.remove).toHaveBeenCalledTimes(1);
    expect(mocks.root.unmount).toHaveBeenCalledTimes(1);
  });

  it("converts an initial SMILES value to Molfile before exposing it to the parent", async () => {
    const wrapper = mount(KetcherEditor, { props: { modelValue: "CCO", disabled: false } });
    await flushPromises();

    expect(mocks.api.setMolecule).toHaveBeenCalledWith("CCO");
    expect(wrapper.emitted("update:modelValue")).toEqual([["MOCK MOLFILE"]]);
  });

  it("does not reload Ketcher when the parent echoes its own Molfile output", async () => {
    const wrapper = mount(KetcherEditor, { props: { modelValue: "CCO", disabled: false } });
    await flushPromises();
    expect(mocks.api.setMolecule).toHaveBeenCalledTimes(1);

    const changeHandler = mocks.changeEvent.add.mock.calls[0]?.[0] as (() => Promise<void>);
    await changeHandler();
    await wrapper.setProps({ modelValue: "MOCK MOLFILE" });
    await flushPromises();

    expect(mocks.api.setMolecule).toHaveBeenCalledTimes(1);
  });

  it("transforms CommonJS calls embedded in Ketcher's ES modules for production", () => {
    const config = readFileSync(resolve(import.meta.dirname, "../vite.config.ts"), "utf8");

    expect(config).toContain("transformMixedEsModules: true");
    expect(config).toContain('global: "globalThis"');
  });
});
