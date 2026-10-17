import { locale } from '../../i18n';

const english: Record<string, string> = {
  '搜索所有 Lineage 中的 Compound': 'Search Compounds across all Lineages',
  'Compound 搜索结果': 'Compound search results',
  '没有匹配的 Lineage 成员。': 'No matching Lineage members.',
  '一键确认 Draft Edge': 'Confirm all Draft Edges',
  'Lineage 未能确认，请重试。': 'Could not confirm the Lineage. Please retry.',
  '筛选当前成员': 'Filter current members',
  '搜索可添加的 Compound': 'Search available Compounds',
};
export function lineageToolsText(source: string): string {
  return locale.value === 'en' ? english[source] ?? source : source;
}
