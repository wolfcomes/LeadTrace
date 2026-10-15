import { t } from '../i18n';

export function reviewVersionStatus(status?: string | null): string {
  const labels: Record<string, string> = {
    pending: '待审批', approve: '已批准', request_changes: '已退回修改',
    awaiting_reviewer: '待 Reviewer 核对补填', supplemented: '补填后已重新提交',
    superseded: '历史提交', unavailable: '版本记录待核对',
  };
  return t(labels[status ?? 'pending'] ?? '版本记录待核对');
}
