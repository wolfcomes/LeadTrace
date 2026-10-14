import { computed, inject, provide, type InjectionKey, type Ref } from "vue";
import { rows, type Row, type ScientificChange } from "./comparison";
interface Focus {
  available: boolean;
  changes: ScientificChange[];
  before: Row;
  after: Row;
}
const key: InjectionKey<Ref<Focus>> = Symbol("frozen-review-focus");
export function provideReviewFocus(value: Ref<Focus>) {
  provide(key, value);
}
export function useReviewFocus() {
  const inherited = inject(key, null);
  const state = inherited ?? computed<Focus>(() => ({
      available: false,
      changes: [],
      before: {},
      after: {},
    }));
  function change(domain: string, id: unknown) {
    return state.value.changes.find(
      (c) =>
        c.domain === domain &&
        (c.id === id || domain === "paper" || domain === "source"),
    );
  }
  function changed(domain: string, id: unknown, fields?: string[]) {
    if (!state.value.available) return true;
    const c = change(domain, id);
    return Boolean(
      c &&
        (!fields ||
          c.kind !== "modified" ||
          c.fields.some((f) => fields.includes(f.key))),
    );
  }
  function pairRows(domain: string, id: unknown) {
    return [state.value.before, state.value.after].flatMap((s) =>
      rows(s, domain).filter((r) => r.id === id),
    );
  }
  function related(domain: string, id: unknown) {
    return (
      changed(domain, id) ||
      pairRows(domain, id).some((r) => changed("evidence", r.evidence_id))
    );
  }
  function sortIds(domain: string, ids: string[]) {
    return [...ids].sort(
      (a, b) => Number(related(domain, b)) - Number(related(domain, a)),
    );
  }
  function sortRows(domain: string, values: Row[]) {
    return [...values].sort((a,b) => Number(related(domain,b.id))-Number(related(domain,a.id)));
  }
  function compoundSection(compoundId: unknown, section: string) {
    const domains: Record<string, string[]> = {
      identity: ["compounds", "compound_highlights"],
      structures: ["structures"],
      originals: ["structure_source_images"],
      activities: ["activities"],
    };
    return (domains[section] ?? []).some((domain) =>
      [state.value.before, state.value.after].some((s) =>
        rows(s, domain).some(
          (r) =>
            (domain === "compounds"
              ? r.id === compoundId
              : r.compound_id === compoundId) && related(domain, r.id),
        ),
      ),
    );
  }
  return { state, hasComparison: Boolean(inherited), change, changed, related, sortIds, sortRows, compoundSection };
}
