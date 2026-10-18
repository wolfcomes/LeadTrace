import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PaperCatalogPage from '../src/admin/PaperCatalogPage.vue';
import ApprovalCenterPage from '../src/approvals/ApprovalCenterPage.vue';
import FilesPage from '../src/admin/FilesPage.vue';
import * as v2 from '../src/v2/api';
import * as admin from '../src/admin/api';
vi.mock('../src/v2/api', () => ({ listAdminPapers: vi.fn(), listAdminSubmissions: vi.fn() }));
vi.mock('../src/admin/api', () => ({ fetchAdminFiles: vi.fn(), fetchFileReferences: vi.fn() }));
const wrappers: ReturnType<typeof mount>[] = [];
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ journals: ['JMC'], years: [2024], volumes: ['67'], issues: ['1'] }), { status: 200 })));
  vi.mocked(v2.listAdminPapers).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
  vi.mocked(v2.listAdminSubmissions).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(admin.fetchAdminFiles).mockResolvedValue([]);
});
afterEach(() => { wrappers.forEach(w => w.unmount()); wrappers.length = 0; vi.clearAllMocks(); vi.unstubAllGlobals(); });
async function render(component: typeof FilesPage | typeof PaperCatalogPage | typeof ApprovalCenterPage, query: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', name: 'admin-papers', component }] });
  await router.push('/' + query);
  await router.isReady();
  const wrapper = mount(component, { global: { plugins: [router] } });
  wrappers.push(wrapper);
  await flushPromises();
  return { wrapper, router };
}
it('catalog composes keyword, filters and page and restores filters from URL', async () => {
  const { wrapper, router } = await render(PaperCatalogPage, '?journal=JMC&year_from=2022&year_to=2024&volume=67&issue=1&assignment_status=assigned&prefill_status=succeeded&page=3&search=kinase');
  expect(v2.listAdminPapers).toHaveBeenLastCalledWith({ journal: 'JMC', year_from: 2022, year_to: 2024, volume: '67', issue: '1', assignment_status: 'assigned', prefill_status: 'succeeded', limit: 20, offset: 40, search: 'kinase' });
  await wrapper.get('input[name=issue]').setValue('2');
  await wrapper.get('[data-paper-filters]').trigger('submit');
  await flushPromises();
  expect(router.currentRoute.value.query).toMatchObject({ issue: '2', page: '1', search: 'kinase' });
  await wrapper.get('input[type=search]').setValue('protease');
  await wrapper.get('[data-admin-paper-filters]').trigger('submit');
  await flushPromises();
  expect(v2.listAdminPapers).toHaveBeenLastCalledWith(expect.objectContaining({ journal: 'JMC', issue: '2', search: 'protease', offset: 0 }));
});
it('approval filters preserve all-submissions scope and discard stale responses', async () => {
  let resolveOld!: (value: { items: never[]; total: number }) => void;
  vi.mocked(v2.listAdminSubmissions).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  const { wrapper, router } = await render(ApprovalCenterPage, '?journal=Old&scope=all');
  await wrapper.get('[name=journal]').setValue('JMC');
  await wrapper.get('[data-paper-filters]').trigger('submit');
  await flushPromises();
  expect(router.currentRoute.value.query.scope).toBe('all');
  expect(v2.listAdminSubmissions).toHaveBeenLastCalledWith({ journal: 'JMC' });
  resolveOld({ items: [], total: 0 });
  await flushPromises();
  expect(wrapper.get('[name=journal]').element).toHaveProperty('value', 'JMC');
  expect(wrapper.get('[data-all-review-submissions]').attributes('aria-pressed')).toBe('true');
});
it('files paginate after filtering and clear filters back to first page', async () => {
  vi.mocked(admin.fetchAdminFiles).mockResolvedValueOnce(Array.from({ length: 51 }, (_, i) => ({ id: String(i), filename: `file-${i}` })));
  const { wrapper, router } = await render(FilesPage, '?journal=JMC&assignment_status=unassigned');
  expect(admin.fetchAdminFiles).toHaveBeenLastCalledWith({ journal: 'JMC', assignment_status: 'unassigned', limit: 51, offset: 0 });
  expect(wrapper.findAll('tbody tr')).toHaveLength(50);
  await wrapper.get('[data-next-page]').trigger('click');
  await flushPromises();
  expect(admin.fetchAdminFiles).toHaveBeenLastCalledWith({ journal: 'JMC', assignment_status: 'unassigned', limit: 51, offset: 50 });
  await wrapper.get('[data-reset-filters]').trigger('click');
  await flushPromises();
  expect(router.currentRoute.value.query).toEqual({ page: '1' });
  expect(admin.fetchAdminFiles).toHaveBeenLastCalledWith({ limit: 51, offset: 0 });
});
