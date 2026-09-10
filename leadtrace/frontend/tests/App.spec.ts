import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../src/App.vue";


function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}


describe("application health state", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders a loading state while readiness is pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

    const wrapper = mount(App);

    expect(wrapper.get("[data-state='loading']").text()).toContain("Connecting");
  });

  it("renders the ready application shell", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(200, {
        status: "ready",
        checks: { asset_root: { status: "ok" }, database: { status: "ok" } },
      })),
    );

    const wrapper = mount(App);
    await flushPromises();

    expect(wrapper.get("[data-state='ready']").text()).toContain("Platform ready");
  });

  it("renders dependency unavailability as a retryable state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(503, {
        status: "unavailable",
        checks: {
          asset_root: { status: "ok" },
          database: { status: "unavailable" },
        },
      })),
    );

    const wrapper = mount(App);
    await flushPromises();

    expect(wrapper.get("[data-state='unavailable']").text()).toContain(
      "Temporarily unavailable",
    );
  });

  it.each([
    [403, "forbidden", "Access denied"],
    [404, "not-found", "Page not found"],
    [500, "error", "Something went wrong"],
  ])("maps HTTP %s to the %s state", async (status, state, message) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(status, {})));

    const wrapper = mount(App);
    await flushPromises();

    expect(wrapper.get(`[data-state='${state}']`).text()).toContain(message);
  });
});
