import { inject, provide, reactive, type InjectionKey } from "vue";
const key: InjectionKey<Map<string, boolean>> = Symbol(
  "paired-review-disclosures",
);
export function provideReviewDisclosures() {
  const state = reactive(new Map<string, boolean>());
  provide(key, state);
  return state;
}
export function useReviewDisclosures() {
  return inject(key, null) ?? reactive(new Map<string, boolean>());
}
