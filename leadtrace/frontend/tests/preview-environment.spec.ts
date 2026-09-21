import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../src/App.vue";
import { ref } from "vue";
import { loadPreviewInstance, previewInstanceKey } from "../src/api/environment";

const options = { global: { stubs: { RouterView: { template: "<div data-router-view />" } } } };

afterEach(() => vi.unstubAllGlobals());

describe("Preview environment", () => {
  it("labels the login and all workspace pages using nonsecret server identity", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      environment: "preview", instance_id: "81000000-0000-4000-8000-000000000001",
      baseline_sha256: "a".repeat(64), frontend_available: true,
    }) }));
    const instance = ref(await loadPreviewInstance());
    const wrapper = mount(App, { global: { ...options.global, provide: { [previewInstanceKey as symbol]: instance } } });
    await flushPromises();
    expect(wrapper.get("[data-preview-environment]").text()).toContain("预览环境");
    expect(wrapper.get("[data-preview-environment]").text()).toContain("人工复核");
    expect(wrapper.get("[data-preview-environment]").attributes("title")).toContain("81000000");
    expect(wrapper.find("[data-router-view]").exists()).toBe(true);
  });

  it("does not label a normal deployment as Preview", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    const instance = ref(await loadPreviewInstance());
    const wrapper = mount(App, { global: { ...options.global, provide: { [previewInstanceKey as symbol]: instance } } });
    await flushPromises();
    expect(wrapper.find("[data-preview-environment]").exists()).toBe(false);
  });

  it("tolerates unavailable environment metadata", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const instance = ref(await loadPreviewInstance());
    const wrapper = mount(App, { global: { ...options.global, provide: { [previewInstanceKey as symbol]: instance } } });
    await flushPromises();
    expect(wrapper.find("[data-router-view]").exists()).toBe(true);
  });
});
