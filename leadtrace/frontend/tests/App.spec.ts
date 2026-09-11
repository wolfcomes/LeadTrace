import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import App from "../src/App.vue";

describe("application root", () => {
  it("provides the active route outlet", () => {
    const wrapper = mount(App, {
      global: { stubs: { RouterView: { template: "<div data-router-view />" } } },
    });

    expect(wrapper.find("[data-router-view]").exists()).toBe(true);
  });
});
