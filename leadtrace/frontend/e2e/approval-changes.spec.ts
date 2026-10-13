import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { expect, test, type Page } from '@playwright/test';
import { adminSubmissionDetail, publicationIds, reviewerEvent } from '../tests/paper-publication-v2-fixtures';

const syntheticPdf = execFileSync(process.env.LEADTRACE_PYTHON || '/data/home/zhangzhiyong/lead_optimization_collection/.worktrees/ai-prefill-tools/.venv/bin/python', ['-c', 'import fitz,sys; d=fitz.open(); [d.new_page(width=600,height=800).insert_text((100,200),"Synthetic evidence",fontsize=20) for _ in range(12)]; sys.stdout.buffer.write(d.tobytes())']);
const syntheticSha = createHash('sha256').update(syntheticPdf).digest('hex');
function fixture() {
 const detail = structuredClone(adminSubmissionDetail) as any;
 detail.submission.snapshot.source.sha256 = syntheticSha;
 for (const item of [...detail.submission.snapshot.evidence, ...detail.submission.snapshot.structure_source_images]) item.source_sha256 = syntheticSha;
 const before = structuredClone(detail.submission.snapshot);
 before.activities[0].value = '125';
 before.evidence[0].page_number = 3;
 before.evidence[0].quoted_text = 'Initial potency report: 125 nM.';
 before.structures[0].status = 'draft'; // Only confirmation; no changed chemistry.
 before.structures[1].status = 'unresolved';
 before.structures[1].smiles = null; before.structures[1].canonical_smiles = null;
 before.structures[1].inchi = null; before.structures[1].inchikey = null;
 detail.submission.snapshot.compounds[0].review_hint = 'Check whether the salt form matches.';
 before.compounds[0].review_hint = 'Check whether the salt form matches.';
 const events = [
  { ...reviewerEvent, id: '40000000-0000-4000-8000-000000000031', entity_type: 'activity', entity_id: publicationIds.activity, action: 'activity.update', before_value: before.activities[0], after_value: detail.submission.snapshot.activities[0] },
  { ...reviewerEvent, id: '40000000-0000-4000-8000-000000000032', entity_type: 'evidence', entity_id: publicationIds.evidence, action: 'evidence.update', before_value: before.evidence[0], after_value: detail.submission.snapshot.evidence[0] },
  { ...reviewerEvent, id: '40000000-0000-4000-8000-000000000033', entity_type: 'structure', entity_id: publicationIds.structureA, before_value: before.structures[0], after_value: detail.submission.snapshot.structures[0] },
  { ...reviewerEvent, id: '40000000-0000-4000-8000-000000000034', entity_type: 'structure', entity_id: publicationIds.structureB, before_value: before.structures[1], after_value: detail.submission.snapshot.structures[1] },
 ];
 detail.change_events = events; detail.reviewer_diff = events;
 detail.comparison = { kind: 'previous_submission', baseline_submission_number: 1, baseline_snapshot: before, events, warnings: [] };
 return detail;
}
async function setup(page: Page, body = fixture()) {
 const scientificWrites: string[] = [];
 await page.route(/\/api\/v[12]\//, async route => {
  const path = new URL(route.request().url()).pathname;
  if (!['GET','HEAD'].includes(route.request().method())) scientificWrites.push(path);
  if (path === '/api/v1/auth/session') return route.fulfill({json:{ user: { username: 'admin', display_name: 'Test Admin', role: 'admin', must_change_password: false }, csrf_token: 'synthetic-csrf' }});
  if (path === `/api/v2/admin/submissions/${publicationIds.submission}`) return route.fulfill({ json: body });
  if (path.endsWith('/source-pdf')) return route.fulfill({contentType:'application/pdf',body:syntheticPdf});
  if (path.startsWith('/api/v1/assets/')) return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="100"><text x="30" y="50">CH3—CH2—OH</text></svg>'});
  return route.fulfill({status:404,json:{error:{code:'NOT_FOUND',message:'Synthetic fixture only'}}});
 });
 await page.goto(`/admin/submissions/${publicationIds.submission}`);
 await expect(page.locator('[data-comparison-summary]')).toBeVisible();
 return scientificWrites;
}

test('Admin sees net changes and evidence before routine confirmations or full content', async ({page}) => {
 const writes = await setup(page);
 const cards = page.locator('[data-change-card]');
 await expect(cards.first()).toBeVisible();
 await expect(page.locator('[data-comparison-summary]')).toContainText('125');
 await expect(page.locator('[data-comparison-summary]')).toContainText('12.5');
 await expect(page.locator('[data-comparison-summary]')).toContainText('Initial potency report');
 await expect(page.locator('[data-comparison-summary]')).toContainText('Lead 1 was optimized');
 await expect(page.locator('[data-remaining-issues]')).toContainText('Check whether the salt form matches.');
 expect(await page.locator('[data-full-submission]').evaluate(el => (el as HTMLDetailsElement).open)).toBe(false);
 expect(await page.locator('[data-change-history]').evaluate(el => (el as HTMLDetailsElement).open)).toBe(false);
 await expect(page.locator('[data-confirmation-summary]')).toBeVisible();
 await page.screenshot({path:'test-results/approval-changes-desktop.png',fullPage:true});
 await page.locator('[data-full-submission] > summary').click();
 await expect(page.locator('[data-submission-lineage]')).toBeVisible();
 expect(writes).toEqual([]);
});

test('Mobile review fits viewport and missing comparison stays explicit', async ({page}) => {
 await page.setViewportSize({width:390,height:844});
 await setup(page);
 expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
 await page.screenshot({path:'test-results/approval-changes-mobile.png',fullPage:true});
 const body = fixture(); body.comparison = {kind:'unavailable',baseline_submission_number:null,baseline_snapshot:null,events:body.change_events,warnings:['History cannot establish a reliable baseline.']};
 await page.route(`**/api/v2/admin/submissions/${publicationIds.submission}*`,route=>route.fulfill({json:body}));
 await page.reload();
 await expect(page.locator('[data-comparison-warning]').first()).toBeVisible();
 await expect(page.locator('[data-comparison-warning]').filter({hasText:'History cannot establish'})).toBeVisible();
 await expect(page.locator('[data-approve-submission]')).toBeDisabled();
});
