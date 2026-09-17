import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";


export const ids = {
  paper: "30000000-0000-4000-8000-000000000001",
  task: "30000000-0000-4000-8000-000000000002",
  workspace: "30000000-0000-4000-8000-000000000003",
  reviewer: "30000000-0000-4000-8000-000000000004",
  asset: "30000000-0000-4000-8000-000000000005",
  compounds: [
    "30000000-0000-4000-8000-000000000011",
    "30000000-0000-4000-8000-000000000012",
    "30000000-0000-4000-8000-000000000013",
    "30000000-0000-4000-8000-000000000014",
  ],
  lineages: [
    "30000000-0000-4000-8000-000000000021",
    "30000000-0000-4000-8000-000000000022",
    "30000000-0000-4000-8000-000000000023",
  ],
  members: [
    "30000000-0000-4000-8000-000000000031",
    "30000000-0000-4000-8000-000000000032",
    "30000000-0000-4000-8000-000000000033",
    "30000000-0000-4000-8000-000000000034",
  ],
  edges: [
    "30000000-0000-4000-8000-000000000041",
    "30000000-0000-4000-8000-000000000042",
    "30000000-0000-4000-8000-000000000043",
  ],
  evidence: [
    "30000000-0000-4000-8000-000000000051",
    "30000000-0000-4000-8000-000000000052",
  ],
  links: [
    "30000000-0000-4000-8000-000000000061",
    "30000000-0000-4000-8000-000000000062",
  ],
  activities: [
    "30000000-0000-4000-8000-000000000071",
    "30000000-0000-4000-8000-000000000072",
  ],
  submission: "30000000-0000-4000-8000-000000000081",
};

export const sectionKeys = ["bibliography", "compounds", "structures", "lineages", "edge_evidence", "activities"] as const;

export function workspace(version = 1, sectionState: "pending" | "completed" | "not_reported" = "completed") {
  return {
    id: ids.workspace,
    review_task_id: ids.task,
    assigned_reviewer_id: ids.reviewer,
    state: "editing",
    version,
    task_status: "assigned",
    bibliography: { paper_id: ids.paper, paper_key: "LT-TASK15", title: "Variable lineage paper", journal: "JMC", publication_year: 2024, volume: "67", issue: "5", doi: null },
    source: { asset_id: ids.asset, source_root_key: "source_pdfs", source_key: "volume67 issue5/task15.pdf", sha256: "c".repeat(64), page_count: 10 },
    sections: sectionKeys.map((section_key) => ({ section_key, state: sectionState, note: null })),
  };
}

export const compounds = ids.compounds.map((id, index) => ({
  id,
  paper_id: ids.paper,
  workspace_id: ids.workspace,
  compound_label: `C${index + 1}`,
  display_name: `Compound ${index + 1}`,
  description: null,
  sort_order: index,
  created_by_kind: "reviewer",
}));

const roles = ["root", "root", "terminal", "terminal"] as const;
export const members = ids.members.map((id, index) => ({
  id,
  paper_id: ids.paper,
  workspace_id: ids.workspace,
  lineage_id: ids.lineages[0],
  compound_id: ids.compounds[index],
  role: roles[index],
  sort_order: index,
}));

const endpoints = [[0, 2], [0, 3], [1, 2]] as const;
export const edges = ids.edges.map((id, index) => ({
  id,
  paper_id: ids.paper,
  workspace_id: ids.workspace,
  lineage_id: ids.lineages[0],
  parent_compound_id: ids.compounds[endpoints[index][0]],
  child_compound_id: ids.compounds[endpoints[index][1]],
  relation_type: "lead_optimization",
  modification_summary: `Change ${index + 1}`,
  review_status: "reviewer_confirmed",
  sort_order: index,
}));

export const lineages = [
  { id: ids.lineages[0], paper_id: ids.paper, workspace_id: ids.workspace, lineage_label: "Series A", description: "Branched series", sort_order: 0, members, edges },
  { id: ids.lineages[1], paper_id: ids.paper, workspace_id: ids.workspace, lineage_label: "Series B", description: null, sort_order: 1, members: [], edges: [] },
];

export const evidence = {
  id: ids.evidence[0], paper_id: ids.paper, workspace_id: ids.workspace, kind: "text", source_sha256: "c".repeat(64), page_number: 2,
  bbox: null, quoted_text: "Compound C1 was optimized to C3.", caption: null, crop_asset_id: null, reviewer_note: null,
};

export const links = ids.links.map((id, index) => ({
  id, paper_id: ids.paper, workspace_id: ids.workspace, edge_id: ids.edges[index], evidence_id: ids.evidence[0], role: "supports",
}));

export const activities = ids.activities.map((id, index) => ({
  id, paper_id: ids.paper, workspace_id: ids.workspace, compound_id: ids.compounds[0], evidence_id: null,
  assay_name: `Assay ${index + 1}`, metric: "IC50", operator: "=", value: `${index + 1}.5`, unit: "nM", context: null, sort_order: index,
}));

export function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "X-Request-ID": "task15-ui" } });
}

export function installReviewer(): void {
  setActivePinia(createPinia());
  useAuthStore().acceptSession({
    user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
    csrf_token: "reviewer-csrf",
  });
}

export async function mountWorkspace(tab: "lineages" | "evidence" | "submit", entity?: string) {
  const router = createAppRouter(createMemoryHistory());
  const entityQuery = entity ? `&entity=${encodeURIComponent(entity)}` : "";
  await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}&tab=${tab}${entityQuery}`);
  await router.isReady();
  const wrapper = mount(App, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}
