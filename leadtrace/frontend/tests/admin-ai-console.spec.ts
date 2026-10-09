import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { locale } from "../src/i18n";
import AiTaskConsole from "../src/admin/AiTaskConsole.vue";
import * as api from "../src/admin/aiTasks";
vi.mock("../src/admin/aiTasks", () => ({
  fetchAiTasks: vi.fn(),
  fetchAiReviewReport: vi.fn(),
  fetchPaperManagement: vi.fn(),
  createAiTask: vi.fn(),
  changeAiConcurrency: vi.fn(),
  cancelAiTask: vi.fn(),
  retryAiTask: vi.fn(),
  deliverAiTask: vi.fn(),
  repairAiTask: vi.fn(),
  acceptAiRepair: vi.fn(),
  recallPaper: vi.fn(),
  archiveResetPaper: vi.fn(),
}));
const preset = {
  id: "deepseek",
  label: "DeepSeek",
  adapter: "dsh",
  model: "deepseek-flash",
  efforts: ["high", "max"],
  default_effort: "max",
  available: true,
  unavailable_reason: null,
};
const management = {
  paper_id: "paper",
  paper_key: "TEST-018",
  workspace_id: "workspace",
  workspace_version: 3,
  task_version: 2,
  assignment_state: "assigned",
  assigned_reviewer_id: "reviewer",
  counts: { compounds: 68, edges: 54 },
  archives: [],
  archive_root: "/private/article-archives",
};
const job = {
  id: "job",
  paper_id: "paper",
  paper_key: "TEST-018",
  paper_title: "Test article",
  workspace_id: "workspace",
  workspace_version: 3,
  action: "review",
  preset_id: "deepseek",
  model: "deepseek-flash",
  reasoning_effort: "max",
  state: "running",
  delivery_state: "not_applicable",
  stage: "running",
  error_code: null,
  error_message: null,
  created_at: "2026-10-08T00:00:00Z",
  started_at: null,
  finished_at: null,
  heartbeat_at: null,
  timeout_seconds: 3600,
  attempt: 1,
  parent_job_id: null,
  result_summary: {},
  can_cancel: true,
  can_retry: false,
};
let wrappers: ReturnType<typeof mount>[] = [];
beforeEach(() => {
  vi.mocked(api.fetchAiTasks).mockResolvedValue({
    items: [],
    total: 0,
    settings: { max_concurrent: 4 },
    worker: { online: true, last_seen_at: null },
    presets: [preset],
  } as never);
  vi.mocked(api.fetchPaperManagement).mockResolvedValue(management as never);
  vi.mocked(api.createAiTask).mockResolvedValue(job as never);
});
afterEach(() => {
  wrappers.forEach((w) => w.unmount());
  wrappers = [];
  vi.useRealTimers();
  vi.clearAllMocks();
  locale.value = "zh-CN";
});
function render(props = {}) {
  const w = mount(AiTaskConsole, {
    props,
    global: { stubs: { RouterLink: true } },
  });
  wrappers.push(w);
  return w;
}
it("uses configured concurrency four and preserves edits through long-running polling", async () => {
  vi.useFakeTimers();
  const w = render();
  await flushPromises();
  expect(w.get("[data-concurrency]").element).toHaveProperty("value", "4");
  await w.get("[data-concurrency]").setValue("6");
  await vi.advanceTimersByTimeAsync(75000);
  expect(api.fetchAiTasks).toHaveBeenCalledTimes(16);
  expect(w.get("[data-concurrency]").element).toHaveProperty("value", "6");
});
it("starts fresh independent review of the current saved version with selected effort", async () => {
  const w = render({ paperId: "paper" });
  await flushPromises();
  await w.get("[data-review-effort]").setValue("high");
  await w.get("[data-start-review]").trigger("click");
  await flushPromises();
  expect(api.createAiTask).toHaveBeenCalledWith(
    "paper",
    expect.objectContaining({
      action: "review",
      preset_id: "deepseek",
      reasoning_effort: "high",
      expected_workspace_version: 3,
      expected_workspace_id: "workspace",
      expected_task_version: 2,
      idempotency_key: expect.any(String),
    }),
  );
  expect(w.text()).toContain("一次新上下文任务");
});
it("requires exact paper key before archiving and resetting", async () => {
  vi.mocked(api.archiveResetPaper).mockResolvedValue({
    ...management,
    assignment_state: "unassigned",
  } as never);
  const w = render({ paperId: "paper" });
  await flushPromises();
  await w.get("[data-open-reset]").trigger("click");
  expect(w.text()).toContain("68");
  expect(w.text()).toContain("/private/article-archives");
  expect(w.get("[data-confirm-reset]").attributes("disabled")).toBeDefined();
  await w.get("[data-reset-paper-key]").setValue("TEST-018");
  await w.get("[data-confirm-reset]").trigger("click");
  await flushPromises();
  expect(api.archiveResetPaper).toHaveBeenCalledWith("paper", {
    expected_workspace_version: 3,
    expected_workspace_id: "workspace",
    expected_task_version: 2,
    confirm_paper_key: "TEST-018",
  });
});
it("shows errors and partial coverage without claiming scientific approval in English", async () => {
  locale.value = "en";
  vi.mocked(api.fetchAiTasks).mockResolvedValue({
    items: [
      {
        ...job,
        state: "partial",
        stage: "coverage_check",
        can_cancel: false,
        can_retry: true,
        error_code: "INCOMPLETE_COVERAGE",
        error_message: "Three compounds not checked",
        result_summary: { missing_compounds: 3 },
      },
    ],
    total: 1,
    settings: { max_concurrent: 4 },
    worker: { online: false, last_seen_at: null },
    presets: [preset],
  } as never);
  const w = render();
  await flushPromises();
  expect(w.text()).toContain("Partial");
  expect(w.text()).toContain("Three compounds not checked");
  expect(w.text()).toContain("INCOMPLETE_COVERAGE");
  expect(w.text()).toContain("Worker offline");
  expect(w.find("[data-retry-job]").exists()).toBe(true);
});

it("shows unavailable models without allowing generation and keeps reviewer selection separate", async () => {
  vi.mocked(api.fetchAiTasks).mockResolvedValue({
    items: [],
    total: 0,
    settings: { max_concurrent: 4 },
    worker: { online: true, last_seen_at: null },
    presets: [
      preset,
      {
        ...preset,
        id: "codex",
        label: "Codex",
        adapter: "codex",
        model: "gpt-test",
        efforts: ["low", "high"],
        default_effort: "high",
      },
      {
        ...preset,
        id: "offline",
        available: false,
        unavailable_reason: "Credentials missing",
      },
    ],
  } as never);
  vi.mocked(api.fetchPaperManagement).mockResolvedValue({
    ...management,
    counts: {},
  } as never);
  const w = render({ paperId: "paper" });
  await flushPromises();
  await w.get("[data-review-model]").setValue("codex");
  expect(w.get("[data-review-effort]").element).toHaveProperty("value", "high");
  expect(w.get("[data-producer-model]").element).toHaveProperty(
    "value",
    "deepseek",
  );
  expect(w.get("[data-producer-effort]").element).toHaveProperty(
    "value",
    "max",
  );
  await w.get("[data-producer-model]").setValue("offline");
  expect(w.get("[data-start-prefill]").attributes("disabled")).toBeDefined();
  expect(w.text()).toContain("Credentials missing");
});
it("keeps task history concise instead of repeating individual findings", async () => {
  vi.mocked(api.fetchAiTasks).mockResolvedValue({
    items: [
      {
        ...job,
        state: "needs_revision",
        can_cancel: false,
        result_summary: {
          missing_review_targets: 3,
          findings: [
            {
              domain: "compound",
              ref: "compound-23",
              verdict: "incorrect",
              reason: "Ring system differs",
            },
          ],
          report_available: true,
        },
      },
    ],
    total: 1,
    settings: { max_concurrent: 4 },
    worker: { online: true, last_seen_at: null },
    presets: [preset],
  } as never);
  const w = render();
  await flushPromises();
  expect(w.text()).not.toContain("compound-23");
  expect(w.text()).not.toContain("Ring system differs");
  expect(w.find("[data-view-report]").exists()).toBe(true);
});
it("can start jobs on the HTTP LAN preview without secure-context randomUUID", async () => {
  const original = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", {
    value: undefined,
    configurable: true,
  });
  try {
    const w = render({ paperId: "paper" });
    await flushPromises();
    await w.get("[data-start-review]").trigger("click");
    await flushPromises();
    expect(api.createAiTask).toHaveBeenCalledWith(
      "paper",
      expect.objectContaining({
        idempotency_key: expect.stringMatching(
          /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
        ),
      }),
    );
  } finally {
    Object.defineProperty(crypto, "randomUUID", {
      value: original,
      configurable: true,
    });
  }
});
it("summarizes legacy reports and keeps full diagnostic rows behind an explicit expansion", async () => {
  vi.mocked(api.fetchAiTasks).mockResolvedValue({
    items: [
      {
        ...job,
        state: "partial",
        can_cancel: false,
        result_summary: { report_available: true },
      },
    ],
    total: 1,
    settings: { max_concurrent: 4 },
    worker: { online: true, last_seen_at: null },
    presets: [preset],
  } as never);
  vi.mocked(api.fetchAiReviewReport).mockResolvedValue({
    job_id: "job",
    reviewed_workspace_version: 3,
    coverage: {
      expected: 68,
      reviewed: 67,
      missing: [{ domain: "compound", ref: "compound-26" }],
    },
    findings: [
      {
        domain: "compound",
        ref: "compound-23",
        verdict: "incorrect",
        reason: "Wrong ring",
        checked_fields: ["smiles"],
      },
    ],
  } as never);
  const w = render();
  await flushPromises();
  await w.get("[data-view-report]").trigger("click");
  await flushPromises();
  expect(api.fetchAiReviewReport).toHaveBeenCalledWith("job");
  expect(w.text()).not.toContain("compound-26");
  expect(w.text()).toContain("Wrong ring");
  expect(w.text()).toContain("67 / 68");
  const diagnostics = w.get("[data-report-diagnostics]");
  (diagnostics.element as HTMLDetailsElement).open = true;
  await diagnostics.trigger("toggle");
  expect(w.text()).toContain("compound-26");
});
it("keeps keyboard focus inside reset confirmation and restores it on Escape", async () => {
  const w = mount(AiTaskConsole, {
    props: { paperId: "paper" },
    attachTo: document.body,
    global: { stubs: { RouterLink: true } },
  });
  wrappers.push(w);
  await flushPromises();
  const opener = w.get("[data-open-reset]");
  (opener.element as HTMLElement).focus();
  await opener.trigger("click");
  await flushPromises();
  expect(document.activeElement).toBe(w.get("[data-reset-paper-key]").element);
  await w
    .get("[data-reset-paper-key]")
    .trigger("keydown", { key: "Tab", shiftKey: true });
  expect(document.activeElement?.textContent).toBe("取消");
  await w.get('[role="dialog"]').trigger("keydown", { key: "Escape" });
  await flushPromises();
  expect(w.find('[role="dialog"]').exists()).toBe(false);
  expect(document.activeElement).toBe(opener.element);
});
it("shows safe server explanations and request IDs when task start fails", async () => {
  const { ApiError } = await import("../src/api/client");
  vi.mocked(api.createAiTask).mockRejectedValueOnce(
    new ApiError(
      409,
      "WORKSPACE_CHANGED",
      "start-conflict",
      "conflict",
      {},
      "The draft changed after this form was opened.",
    ),
  );
  const w = render({ paperId: "paper" });
  await flushPromises();
  await w.get("[data-start-review]").trigger("click");
  await flushPromises();
  expect(w.text()).toContain("The draft changed after this form was opened.");
  expect(w.text()).toContain("start-conflict");
});
it("recall keeps the exact workspace identity shown when the dialog opened", async () => {
  vi.useFakeTimers();
  vi.mocked(api.recallPaper).mockResolvedValue(management as never);
  const w = render({ paperId: "paper" });
  await flushPromises();
  await w.get("[data-recall]").trigger("click");
  vi.mocked(api.fetchPaperManagement).mockResolvedValue({
    ...management,
    workspace_id: "replacement",
    workspace_version: 3,
    task_version: 1,
    assignment_state: "unassigned",
  } as never);
  await vi.advanceTimersByTimeAsync(5000);
  await w.get("[data-confirm-recall]").trigger("click");
  await flushPromises();
  expect(api.recallPaper).toHaveBeenCalledWith("paper", {
    expected_workspace_id: "workspace",
    expected_workspace_version: 3,
    expected_task_version: 2,
  });
});
it("binds initial generation explicitly to absence of a workspace", async () => {
  vi.mocked(api.fetchPaperManagement).mockResolvedValue({
    ...management,
    workspace_id: null,
    workspace_version: null,
    task_version: null,
    assignment_state: "unassigned",
    assigned_reviewer_id: null,
    counts: {},
  } as never);
  const w = render({ paperId: "paper" });
  await flushPromises();
  expect(w.get("[data-start-review]").attributes("disabled")).toBeDefined();
  await w.get("[data-start-prefill]").trigger("click");
  await flushPromises();
  expect(api.createAiTask).toHaveBeenCalledWith(
    "paper",
    expect.objectContaining({
      action: "prefill",
      expected_workspace_id: null,
      expected_workspace_version: null,
      expected_task_version: null,
    }),
  );
});

it.each(["zh-CN", "en"])("shows imported draft and producer findings without a failure alert (%s)", async (language) => {
  locale.value = language as "zh-CN" | "en";
  vi.mocked(api.fetchAiTasks).mockResolvedValue({
    items: [{ ...job, action: "prefill", state: "needs_revision", stage: "needs_revision",
      delivery_state: "applied", can_cancel: false, can_retry: false,
      result_summary: { report_available: true, scientific_approval: false, missing_compounds: 1 } }],
    total: 1, settings: { max_concurrent: 4 }, worker: { online: true, last_seen_at: null }, presets: [preset],
  } as never);
  vi.mocked(api.fetchAiReviewReport).mockResolvedValue({
    report_kind: "prefill", job_id: "job", reviewed_workspace_version: 4,
    candidate_file_sha256: "a".repeat(64), status: "needs_revision", scientific_approval: false,
    coverage_known: true, coverage: { expected: 2, reviewed: 1, missing: [{ domain: "compound", ref: "unknown-metabolite" }] },
    checks: [{ check_id: "structure_identity", status: "unresolved", details: "Structure requires review" }],
    issue_counts: { blocking: 2, review: 1 }, findings_total: 1, findings_truncated: false,
    findings: [{ domain: "COMPOUND_COVERAGE_INCOMPLETE", ref: "payload.compounds", verdict: "blocking", reason: "Missing identity preserved" }],
  } as never);
  const w = render(); await flushPromises();
  expect(w.text()).toContain(language === "en" ? "Imported · review required" : "已导入，待审核");
  expect(w.find("[data-retry-job]").exists()).toBe(false);
  await w.get("[data-view-report]").trigger("click"); await flushPromises();
  expect(w.text()).toContain(language === "en" ? "Generation and self-check report" : "生成与自检报告");
  expect(w.text()).not.toContain("unknown-metabolite");
  expect(w.text()).not.toContain("Structure requires review");
  expect(w.text()).toContain("Missing identity preserved");
  expect(w.find('[role="alert"]').exists()).toBe(false);
  expect(w.text()).toContain(language === "en" ? "Draft import is not scientific approval" : "导入草稿不代表科学审核通过");
});

it('retries delivery without starting a new model task', async () => {
  vi.mocked(api.fetchAiTasks).mockResolvedValue({items:[{...job,action:'prefill',state:'failed',delivery_state:'not_applied',error_code:'DELIVERY_WRITE_FAILED',can_cancel:false,can_retry:true,can_deliver:true}],total:1,settings:{max_concurrent:4},worker:{online:true,last_seen_at:null},presets:[preset]} as never);
  vi.mocked(api.deliverAiTask).mockResolvedValue({...job,delivery_state:'applied'} as never);
  const w=render();await flushPromises();
  expect(w.text()).toContain('使用已保存的生成结果，不重新调用模型');
  await w.get('[data-deliver-job]').trigger('click');await flushPromises();
  expect(api.deliverAiTask).toHaveBeenCalledWith('job');
  expect(api.retryAiTask).not.toHaveBeenCalled();
  expect(api.createAiTask).not.toHaveBeenCalled();
});

const overview = {
  schema_version: 1, basis: 'independent_review',
  entities: [{ domain: 'compounds', total: 81, supported: 60, incorrect: 4, uncertain: 7, unreviewed: 10, flagged: 11 },
    { domain: 'edges', total: 92, supported: 72, incorrect: 5, uncertain: 5, unreviewed: 10, flagged: 10 }],
  compound_coverage: { known: true, covered: 81, expected: 99, percent: 81.8 },
  audit_coverage: { known: true, checked: 153, expected: 173, percent: 88.4 },
  issue_groups: [{ code: 'STRUCTURE_IDENTITY', count: 11 }], highlights: [{code:'STRUCTURE_IDENTITY',ref:'compound:23',summary:'Ring identity needs attention'}], unique_crop_regions: 132,
};
function reportJob(overrides = {}) {
  vi.mocked(api.fetchAiTasks).mockResolvedValue({items: [{...job, state: 'needs_revision', can_cancel: false, result_summary: {report_available: true}, ...overrides}], total: 1, settings: {max_concurrent: 4}, worker: {online: true, last_seen_at: null}, presets: [preset]} as never);
}
it.each(['zh-CN', 'en'])('shows aggregate entity, reliability and coverage data without a findings flood (%s)', async language => {
  locale.value = language as 'zh-CN' | 'en';
  reportJob();
  vi.mocked(api.fetchAiReviewReport).mockResolvedValue({job_id:'job', reviewed_workspace_version:3, coverage:{expected:173, reviewed:153, missing:[]}, findings:Array.from({length:60}, (_,i)=>({domain:'compound',ref:`private-row-${i}`,verdict:'uncertain',reason:`Long reason ${i}`})), overview} as never);
  const w=render(); await flushPromises(); await w.get('[data-view-report]').trigger('click'); await flushPromises();
  expect(w.get('[data-report-entity="compounds"]').text()).toContain('81');
  expect(w.get('[data-report-entity="compounds"]').text()).toContain('60');
  expect(w.text()).toContain('81.8%'); expect(w.text()).toContain('88.4%');
  expect(w.text()).toContain(language==='en'?'Supported by AI review':'AI复核支持');
  expect(w.text()).not.toContain('private-row-');
  expect(w.text()).toContain('Ring identity needs attention');
});
it('does not offer a second repair invocation even for old review metadata', async () => {
  reportJob({can_repair:true});
  const w = mount(AiTaskConsole); await flushPromises();
  expect(w.find('[data-start-repair]').exists()).toBe(false);
  expect(api.repairAiTask).not.toHaveBeenCalled();
});

it('accepts the displayed concrete proposal hash without another model call', async () => {
  reportJob({action:'review',state:'proposal_ready',can_accept:true});
  vi.mocked(api.fetchAiReviewReport).mockResolvedValue({report_kind:'review',repair_proposal_status:'ready',job_id:'job',reviewed_workspace_version:3,coverage:{expected:0,reviewed:0,missing:[]},findings:[],proposal:{sha256:'b'.repeat(64),counts:{compounds:{added:0,updated:1,removed:0}},total_changes:1,changes:[{domain:'compounds',ref:'compound:23',action:'update',before:{smiles:'C'},after:{smiles:'CC'}}],remaining_findings:2}} as never);
  vi.mocked(api.acceptAiRepair).mockResolvedValue({...job,action:'repair',delivery_state:'applied'} as never);
  const w=render(); await flushPromises();
  expect(w.find('[data-accept-repair]').exists()).toBe(false);
  await w.get('[data-view-report]').trigger('click'); await flushPromises();
  expect(w.text()).toContain('待接受'); expect(w.text()).toContain('接受全部修改并更新草稿');
  expect(w.get('[data-proposal-diff]').attributes('open')).toBeUndefined();
  expect(w.get('[data-proposal-diff]').text()).toContain('更新');
  expect(w.text()).toContain('修补后自检仍有 2 项提示');
  await w.get('[data-accept-repair]').trigger('click'); await flushPromises();
  expect(api.acceptAiRepair).toHaveBeenCalledWith('job','b'.repeat(64));
  expect(api.repairAiTask).not.toHaveBeenCalled(); expect(api.createAiTask).not.toHaveBeenCalled();
  expect(w.emitted('changed')).toHaveLength(1);
});
it('does not imply independent support when only producer checks exist', async () => {
  reportJob({action:'prefill'});
  vi.mocked(api.fetchAiReviewReport).mockResolvedValue({report_kind:'prefill',job_id:'job',reviewed_workspace_version:3,coverage:{expected:99,reviewed:81,missing:[]},findings:[],overview:{...overview,basis:'producer',entities:[{domain:'compounds',total:81,supported:null,incorrect:null,uncertain:null,unreviewed:81,flagged:15}],audit_coverage:{known:false,checked:0,expected:0,percent:null}}} as never);
  const w=render(); await flushPromises(); await w.get('[data-view-report]').trigger('click'); await flushPromises();
  expect(w.get('[data-report-entity="compounds"]').findAll('td')[1].text()).toBe('—');
  expect(w.text()).toContain('未被标记不代表已经独立核实');
});
it('leaves proposal visible and emits no draft change when acceptance conflicts', async () => {
  reportJob({action:'review',state:'proposal_ready',can_accept:true});
  vi.mocked(api.fetchAiReviewReport).mockResolvedValue({job_id:'job',reviewed_workspace_version:3,coverage:{expected:0,reviewed:0,missing:[]},findings:[],proposal:{sha256:'c'.repeat(64),counts:{edges:{added:0,updated:1,removed:0}},total_changes:1,changes:[],remaining_findings:0}} as never);
  vi.mocked(api.acceptAiRepair).mockResolvedValue({...job,delivery_state:'not_applied',error_code:'WORKSPACE_CHANGED',error_message:'Draft version changed'} as never);
  const w=render(); await flushPromises(); await w.get('[data-view-report]').trigger('click'); await flushPromises();
  await w.get('[data-accept-repair]').trigger('click'); await flushPromises();
  expect(w.get('[role="alert"]').text()).toContain('WORKSPACE_CHANGED');
  expect(w.emitted('changed')).toBeUndefined();
  expect(w.find('[data-repair-proposal]').exists()).toBe(true);
});


it.each(['unavailable', 'no_changes'] as const)('preserves the audit view when proposal is %s', async (status) => {
  reportJob({action:'review',state:status==='unavailable'?'partial':'needs_revision'});
  const {aiReviewReportSchema}=await vi.importActual<typeof import('../src/admin/aiTasks')>('../src/admin/aiTasks');
  const response=aiReviewReportSchema.parse({report_kind:'review',job_id:'job',reviewed_workspace_version:3,coverage:{expected:1,reviewed:1,missing:[]},findings:[],proposal:null,repair_proposal_status:status,repair_proposal_reason:status==='no_changes'?'Source evidence is inconclusive.':null});
  vi.mocked(api.fetchAiReviewReport).mockResolvedValue(response);
  const w=render(); await flushPromises(); await w.get('[data-view-report]').trigger('click'); await flushPromises();
  expect(w.find('[data-report-overview]').exists()).toBe(true);
  expect(w.find('[data-accept-repair]').exists()).toBe(false);
  expect(w.find('[data-start-repair]').exists()).toBe(false);
  expect(w.text()).toContain('修改前草稿');
  expect(w.find(status==='unavailable'?'[data-proposal-unavailable]':'[data-proposal-no-changes]').exists()).toBe(true);
  if(status==='no_changes')expect(w.text()).toContain('Source evidence is inconclusive.');
});
