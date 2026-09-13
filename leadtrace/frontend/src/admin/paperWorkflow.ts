import type { AdminPaperWorkflow } from "./api";


export const adminPaperWorkflowStates: ReadonlyArray<{
  value: AdminPaperWorkflow;
  label: string;
  short: string;
}> = [
  { value: "initial", label: "初始状态", short: "初始" },
  { value: "ai_baseline_unassigned", label: "AI 提取基线（未分配）", short: "未分配" },
  { value: "ai_baseline_in_review", label: "AI 提取基线（已分配，人工核验进行中）", short: "核验中" },
  { value: "human_review_pending_approval", label: "人工核验结束（待批）", short: "待审批" },
  { value: "admin_approved", label: "Admin 已批准", short: "已批准" },
];

const labels = new Map(
  adminPaperWorkflowStates.map((entry) => [entry.value, entry.label]),
);

export function adminPaperWorkflowLabel(state: AdminPaperWorkflow): string {
  return labels.get(state) ?? state;
}
