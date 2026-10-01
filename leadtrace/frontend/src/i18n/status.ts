import { t, locale } from './index';

/** Presentation of finite application codes only; never translate scientific free text. */
const labels: Readonly<Record<string, string>> = {
  visitor: '访客', reviewer: '核查员', admin: '管理员',
  draft: '草稿', confirmed: '已确认', unresolved: '未解决', unspecified: '未指定',
  root: '起点', intermediate: '中间节点', terminal: '终点',
  queued: '已排队', running: '运行中', succeeded: '已完成', failed: '失败',
  success: '成功', failure: '失败', pending: '待处理', approved: '已批准',
  enabled: '启用', disabled: '已停用', healthy: '正常', ok: '正常', degraded: '异常', unavailable: '不可用',
  verified: '已验证', missing: '缺失', corrupt: '损坏', registered: '已登记',
  database: '数据库', assets: '资产存储', asset_store: '资产存储', jobs: '任务队列', publications: '发布状态',
  text: '文本', table: '表格', figure: '图', scheme: '合成图式', supporting: '支持', contradicting: '反驳', context: '上下文',
};
export function statusLabel(value: unknown): string {
  const code = value == null ? '—' : String(value);
  if (locale.value === 'zh-CN') return code;
  return labels[code] ? t(labels[code]) : code;
}
