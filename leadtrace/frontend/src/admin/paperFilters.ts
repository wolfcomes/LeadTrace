import { computed, inject, ref } from 'vue';
import { routeLocationKey, routerKey, type LocationQuery, type LocationQueryRaw } from 'vue-router';
import { z } from 'zod';
import { apiRequest } from '../api/client';

export const assignmentStatuses = ['assigned', 'unassigned'] as const;
export const prefillStatuses = ['not_started', 'queued', 'running', 'succeeded', 'failed', 'superseded'] as const;
export interface PaperFilterParams {
  journal?: string; year_from?: number; year_to?: number; volume?: string; issue?: string;
  assignment_status?: typeof assignmentStatuses[number]; prefill_status?: typeof prefillStatuses[number];
}
export interface PaperFilterValues {
  journal: string; year_from: string; year_to: string; volume: string; issue: string;
  assignment_status: '' | typeof assignmentStatuses[number]; prefill_status: '' | typeof prefillStatuses[number];
}
const keys = ['journal', 'year_from', 'year_to', 'volume', 'issue', 'assignment_status', 'prefill_status'] as const;
export function filtersFromQuery(query: LocationQuery): PaperFilterValues {
  const result = Object.fromEntries(keys.map(key => [key, typeof query[key] === 'string' ? query[key] : ''])) as unknown as PaperFilterValues;
  if (!assignmentStatuses.includes(result.assignment_status as typeof assignmentStatuses[number])) result.assignment_status = '';
  if (!prefillStatuses.includes(result.prefill_status as typeof prefillStatuses[number])) result.prefill_status = '';
  return result;
}
export function filterParams(filters: PaperFilterValues): PaperFilterParams {
  return Object.fromEntries(keys.flatMap<[string, string | number]>(key => {
    const value = filters[key].trim();
    if (!value) return [];
    if (key === 'year_from' || key === 'year_to') return /^\d{4}$/.test(value) && Number(value) >= 1000 ? [[key, Number(value)]] : [];
    return [[key, value]];
  }));
}
export function filterQuery(query: LocationQuery, filters: PaperFilterValues): LocationQueryRaw {
  const next: LocationQueryRaw = { ...query, page: '1' };
  keys.forEach(key => delete next[key]);
  return { ...next, ...filterParams(filters) };
}
export function withPaperQuery(path: string, params: PaperFilterParams & { limit?: number; offset?: number; paper_id?: string } = {}): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined) query.set(key, String(value)); });
  return query.size ? `${path}?${query}` : path;
}
const optionsSchema = z.object({ journals: z.array(z.string()), years: z.array(z.number()), volumes: z.array(z.string()), issues: z.array(z.string()) });
export type PaperFilterOptions = z.infer<typeof optionsSchema>;
export function fetchPaperFilterOptions(): Promise<PaperFilterOptions> {
  return apiRequest('/api/v2/admin/papers/filter-options', optionsSchema);
}
/** Use URL state in pages; standalone embedded consoles can use local state. */
export function usePaperFilters() {
  const route = inject(routeLocationKey, undefined);
  const router = inject(routerKey, undefined);
  const localQuery = ref<LocationQuery>({});
  const query = computed(() => route?.query ?? localQuery.value);
  const filters = computed(() => filtersFromQuery(query.value));
  const params = computed(() => filterParams(filters.value));
  const page = computed(() => {
    const value = Number(query.value.page);
    return Number.isSafeInteger(value) && value > 0 ? value : 1;
  });
  async function replace(next: LocationQueryRaw) {
    if (router) await router.replace({ query: next });
    else localQuery.value = Object.fromEntries(Object.entries(next).map(([key, value]) => [key, value == null ? null : String(value)]));
  }
  return { query, filters, params, page, apply: (value: PaperFilterValues) => replace(filterQuery(query.value, value)), goToPage: (value: number) => replace({ ...query.value, page: String(value) }), replace };
}
