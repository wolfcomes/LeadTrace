import { expect, it } from "vitest";
import { catalogReviewSchema, assignmentResponseSchema } from "../src/v2/types";
const id = "10000000-0000-4000-8000-000000000001";
const sections = [
  "bibliography",
  "compounds",
  "structures",
  "lineages",
  "edge_evidence",
  "activities",
].map((section_key) => ({ section_key, state: "pending", note: null }));
it("accepts an unassigned editing draft in the catalog and assignment response", () => {
  expect(
    catalogReviewSchema.safeParse({
      review_task_id: id,
      workspace_id: id,
      assigned_reviewer_id: null,
      assignee_display_name: null,
      task_status: "unassigned",
      workspace_state: "editing",
      sections_resolved: 0,
      sections_total: 6,
      submission_state: "not_submitted",
    }).success,
  ).toBe(true);
  expect(
    assignmentResponseSchema.safeParse({
      review_task_id: id,
      workspace_id: id,
      paper_id: id,
      assigned_reviewer_id: null,
      task_status: "unassigned",
      task_version: 1,
      workspace_state: "editing",
      workspace_version: 1,
      sections,
    }).success,
  ).toBe(true);
});
