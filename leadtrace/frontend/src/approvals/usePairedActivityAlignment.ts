import { nextTick, onBeforeUnmount, onMounted, watch, type Ref } from "vue";
/** Align complete activity rows, including their evidence, by frozen activity ID. */
export function usePairedActivityAlignment(
  host: Ref<HTMLElement | undefined>,
  identity: () => unknown,
) {
  let observer: ResizeObserver | undefined,
    frame = 0,
    disposed = false;
  function align() {
    frame = 0;
    if (!host.value) return;
    const groups = new Map<string, HTMLElement[]>();
    for (const row of host.value.querySelectorAll<HTMLElement>(
      "[data-activity-id]",
    )) {
      const id = row.dataset.activityId!;
      groups.set(id, [...(groups.get(id) ?? []), row]);
    }
    for (const group of groups.values()) {
      const height = Math.max(
        ...group.map((row) => {
          const content = row.querySelector<HTMLElement>(
            "[data-activity-content]",
          );
          const style = getComputedStyle(row);
          return (
            (content?.getBoundingClientRect().height ?? 0) +
            [
              "paddingTop",
              "paddingBottom",
              "borderTopWidth",
              "borderBottomWidth",
            ].reduce(
              (total, key) =>
                total +
                (parseFloat(
                  style[key as keyof CSSStyleDeclaration] as string,
                ) || 0),
              0,
            )
          );
        }),
      );
      for (const row of group) row.style.minHeight = `${height}px`;
    }
  }
  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(align);
  }
  async function observe() {
    await nextTick();
    if (disposed) return;
    observer?.disconnect();
    if (!host.value || typeof ResizeObserver === "undefined") return;
    observer = new ResizeObserver(schedule);
    observer.observe(host.value);
    host.value
      .querySelectorAll("[data-activity-content]")
      .forEach((el) => observer!.observe(el));
    schedule();
  }
  watch(identity, observe);
  watch(host, observe);
  onMounted(observe);
  onBeforeUnmount(() => {
    disposed = true;
    cancelAnimationFrame(frame);
    observer?.disconnect();
  });
}
