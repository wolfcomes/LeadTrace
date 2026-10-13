import { nextTick, onBeforeUnmount, watch, type Ref } from "vue";
const dialogs: symbol[] = [];
let previousOverflow = "";
/** Nested evidence dialogs retain the enclosing lineage view and keyboard focus. */
export function useModalFocus(
  open: Ref<boolean>,
  host: Ref<HTMLElement | undefined>,
) {
  const token = Symbol("approval-dialog");
  let restore: HTMLElement | null = null;
  const controls = () =>
    Array.from(
      host.value?.querySelectorAll<HTMLElement>(
        'button:not([disabled]),a[href],input:not([disabled]),select,textarea,[tabindex="0"]',
      ) ?? [],
    ).filter((el) => !el.closest("[hidden]"));
  function close() {
    const index = dialogs.indexOf(token);
    if (index < 0) return;
    dialogs.splice(index, 1);
    window.removeEventListener("keydown", keydown, true);
    if (!dialogs.length) document.body.style.overflow = previousOverflow;
    restore?.focus();
  }
  function keydown(event: KeyboardEvent) {
    if (dialogs.at(-1) !== token) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      open.value = false;
    }
    if (event.key !== "Tab") return;
    const elements = controls(),
      first = elements[0],
      last = elements.at(-1);
    if (!first) {
      event.preventDefault();
      host.value?.focus();
      return;
    }
    if (
      event.shiftKey &&
      (document.activeElement === first ||
        !host.value?.contains(document.activeElement))
    ) {
      event.preventDefault();
      last?.focus();
    } else if (
      !event.shiftKey &&
      (document.activeElement === last ||
        !host.value?.contains(document.activeElement))
    ) {
      event.preventDefault();
      first.focus();
    }
  }
  watch(open, async (value) => {
    if (!value) {
      close();
      return;
    }
    restore =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    if (!dialogs.length) {
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    dialogs.push(token);
    window.addEventListener("keydown", keydown, true);
    await nextTick();
    if (open.value) (controls()[0] ?? host.value)?.focus();
  });
  onBeforeUnmount(close);
}
