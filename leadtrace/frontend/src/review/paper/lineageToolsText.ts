import { locale } from '../../i18n';

const english: Record<string, string> = {
  '搜索所有 Lineage 中的 Compound': 'Search Compounds across all Lineages',
  'Compound 搜索结果': 'Compound search results',
  '没有匹配的 Lineage 成员。': 'No matching Lineage members.',
  '已核对关系图，标记此 Lineage 已查看': 'I have checked the graph — mark this Lineage as viewed',
  '筛选当前成员': 'Filter current members',
  '搜索可添加的 Compound': 'Search available Compounds',
};
export function lineageToolsText(source: string): string {
  return locale.value === 'en' ? english[source] ?? source : source;
}
