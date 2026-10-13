import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import FrozenSubmissionScope from "../src/approvals/FrozenSubmissionScope.vue";
import { useFrozenPdfPool } from "../src/approvals/frozenPdf";
afterEach(() => vi.unstubAllGlobals());
describe("frozen submission PDF ownership", () => {
  it("shares one bounded PDF pool across comparison and full-content siblings and releases it on navigation", async () => {
    const pools: ReturnType<typeof useFrozenPdfPool>[] = [];
    const Probe = defineComponent({
      setup() {
        pools.push(useFrozenPdfPool());
        return () => null;
      },
    });
    const Comparison = defineComponent({
      setup() {
        return () => h("section", [h(Probe)]);
      },
    });
    const wrapper = mount(FrozenSubmissionScope, {
      slots: {
        default: () => [h(Comparison), h("section", [h(Probe), h(Probe)])],
      },
    });
    expect(pools).toHaveLength(3);
    expect(new Set(pools).size).toBe(1);
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url, options) => {
        signal = options.signal;
        return new Promise((_resolve, reject) =>
          signal!.addEventListener("abort", () => reject(new Error("aborted"))),
        );
      }),
    );
    const pending = pools[0].document("/source", "a".repeat(64));
    wrapper.unmount();
    expect(signal?.aborted).toBe(true);
    await expect(pending).rejects.toThrow("aborted");
    await expect(pools[0].document("/source", "a".repeat(64))).rejects.toThrow(
      "disposed",
    );
    const next = mount(FrozenSubmissionScope, {
      slots: { default: () => h(Probe) },
    });
    expect(pools[3]).not.toBe(pools[0]);
    next.unmount();
  });
});
