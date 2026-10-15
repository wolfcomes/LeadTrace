import { expect, test } from '@playwright/test';
import { adminSubmissionDetail, publicationIds } from '../tests/paper-publication-v2-fixtures';

test('Reviewer version navigation separates additions and makes historical versions read-only', async ({ page }) => {
  const first: any = structuredClone(adminSubmissionDetail);
  const second: any = structuredClone(adminSubmissionDetail);
  first.submission.id = '00000000-0000-4000-8000-000000000777';
  first.submission.submission_number = 1;
  first.submission.submitted_at = '2026-10-10T02:00:00Z';
  const prefill = structuredClone(first.submission.snapshot);
  prefill.paper.abstract = 'Synthetic AI addition for interface verification.';
  second.submission.snapshot = structuredClone(prefill);
  second.submission.snapshot.activities[0].value = '8';
  second.submission.submission_number = 4;
  second.submission.submitted_at = '2026-10-15T04:00:00Z';
  const version = (d: any, round: number, status: string) => ({
    id: d.submission.id, paper_id: d.submission.paper_id, workspace_id: d.submission.workspace_id,
    submission_number: d.submission.submission_number, round_number: round,
    submitted_by_id: d.submission.submitted_by_id, submitted_by_name: 'Test Reviewer',
    submitted_at: d.submission.submitted_at, content_hash: d.submission.content_hash,
    reviewer_note: d.submission.reviewer_note, status, decision: null, followup_decision: null,
  });
  const versions = [version(first, 1, 'supplemented'), version(second, 2, 'pending')];
  const supplement = { count: 2, submitted_at: '2026-10-14T04:00:00Z', snapshot: prefill,
    comparison: { kind: 'previous_submission', baseline_submission_number: null,
      baseline_snapshot: first.submission.snapshot, events: [], warnings: [] } };
  first.review_rounds = { requested_submission_id: first.submission.id, selected_round_number: 1,
    versions, can_decide: false, supplements: [{ ...supplement, phase: 'after_submission' }], warnings: [] };
  second.review_rounds = { requested_submission_id: second.submission.id, selected_round_number: 2,
    versions, can_decide: true, supplements: [{ ...supplement, phase: 'before_submission' }], warnings: [] };
  first.comparison = { kind: 'reviewer_start', baseline_submission_number: null,
    baseline_snapshot: first.submission.snapshot, events: [], warnings: [] };
  second.comparison = { kind: 'previous_submission', baseline_submission_number: 1,
    baseline_snapshot: prefill, events: [], warnings: [] };
  const writes: string[] = [];
  await page.route(/\/api\/v[12]\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (!['GET', 'HEAD'].includes(route.request().method())) writes.push(path);
    if (path === '/api/v1/auth/session') return route.fulfill({ json: {
      user: { username: 'admin', display_name: 'Admin', role: 'admin', must_change_password: false }, csrf_token: 'fixture' } });
    if (path === `/api/v2/admin/submissions/${first.submission.id}`) return route.fulfill({ json: first });
    if (path === `/api/v2/admin/submissions/${publicationIds.submission}`) return route.fulfill({ json: second });
    return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: 'Fixture only', request_id: 'fixture', details: {} } });
  });
  await page.goto(`/admin/submissions/${publicationIds.submission}`);
  await expect(page.locator('[data-review-version-navigation]')).toContainText('第 2 / 2 次提交');
  await expect(page.locator('[data-comparison-summary]').first()).toContainText('1 项实质修改');
  await expect(page.locator('[data-ai-supplements]')).not.toHaveAttribute('open');
  await expect(page.locator('[data-ai-supplements] .comparison-counts')).toHaveCount(0);
  await page.locator('[data-decision-reason]').fill('Current version only');
  await page.locator('[data-previous-review-version]').click();
  await expect(page.locator('[data-review-version-navigation]')).toContainText('第 1 / 2 次提交');
  await expect(page.locator('[data-approve-submission]')).toHaveCount(0);
  await expect(page.locator('[data-historical-review]')).toContainText('只读');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
  await page.locator('[data-next-review-version]').click();
  await expect(page.locator('[data-decision-reason]')).toHaveValue('');
  await expect(page.locator('[data-review-version-navigation]')).toContainText('第 2 / 2 次提交');
  expect(writes).toEqual([]);
});
