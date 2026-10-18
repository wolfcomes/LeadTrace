import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, expect, it, vi } from 'vitest';
import PaperFilters from '../src/admin/PaperFilters.vue';
import { filtersFromQuery, filterQuery, filterParams } from '../src/admin/paperFilters';
afterEach(() => vi.unstubAllGlobals());
it('round trips filters, preserves unrelated URL state and resets pagination', () => {
  const filters = filtersFromQuery({ journal: 'JMC', year_from: '2022', year_to: '2025', volume: 'S1', issue: '2-3', assignment_status: 'assigned', prefill_status: 'succeeded' });
  expect(filterParams(filters)).toEqual({ ...filters, year_from: 2022, year_to: 2025 });
  expect(filterQuery({ search: 'kinase', page: '8', scope: 'all' }, filters)).toMatchObject({ search: 'kinase', page: '1', scope: 'all', volume: 'S1' });
  expect(filterQuery({ journal: 'JMC', page: '8', search: 'kinase' }, filtersFromQuery({}))).toEqual({ search: 'kinase', page: '1' });
});
it('ignores unsupported status values from URLs', () => {
  expect(filtersFromQuery({ assignment_status: 'admin', prefill_status: 'revise' })).toMatchObject({ assignment_status: '', prefill_status: '' });
});
it('prevents inverted year ranges and applies exact bibliographic text', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ journals: ['JMC'], years: [2024], volumes: ['S1'], issues: ['2-3'] }), { status: 200 })));
  const wrapper = mount(PaperFilters, { props: { modelValue: filtersFromQuery({}) } });
  await flushPromises();
  await wrapper.get('[name=year_from]').setValue('2025');
  await wrapper.get('[name=year_to]').setValue('2024');
  await wrapper.get('form').trigger('submit');
  expect(wrapper.emitted('apply')).toBeUndefined();
  expect(wrapper.get('[role=alert]').text()).toContain('年份');
  await wrapper.get('[name=year_to]').setValue('2026');
  await wrapper.get('[name=volume]').setValue('S1');
  await wrapper.get('form').trigger('submit');
  expect(wrapper.emitted('apply')?.[0]?.[0]).toMatchObject({ volume: 'S1', year_from: '2025', year_to: '2026' });
  await wrapper.get('[data-reset-filters]').trigger('click');
  expect(wrapper.emitted('apply')?.[1]?.[0]).toEqual(filtersFromQuery({}));
  wrapper.unmount();
});

it('does not send publication years below API bounds', () => {
  expect(filterParams(filtersFromQuery({ year_from: '999', year_to: '2024' }))).toEqual({ year_to: 2024 });
});
