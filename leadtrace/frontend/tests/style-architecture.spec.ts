import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";


const frontendRoot = resolve(import.meta.dirname, "..");

function source(path: string): string {
  return readFileSync(resolve(frontendRoot, path), "utf8");
}

function vueFiles(directory = "src"): string[] {
  return readdirSync(resolve(frontendRoot, directory), { withFileTypes: true }).flatMap((entry) => {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory()) return vueFiles(path);
    return entry.isFile() && entry.name.endsWith(".vue") ? [path] : [];
  });
}

function matchingVueLines(pattern: RegExp): string[] {
  return vueFiles().flatMap((path) => source(path)
    .split("\n")
    .filter((line) => pattern.test(line))
    .map((line) => `${path}:${line.trim()}`));
}

describe("centralized visual system", () => {
  it("loads the visual layers once from the application entrypoint", () => {
    const mainSource = source("src/main.ts");

    expect(mainSource).toContain('import "./styles/tokens.css"');
    expect(mainSource).toContain('import "./styles/base.css"');
    expect(mainSource).toContain('import "./styles/components.css"');
    expect(mainSource).toContain('import "./styles/layouts.css"');
  });

  it("keeps shared controls and page chrome in global stylesheets", () => {
    const componentStyles = source("src/styles/components.css");
    const layoutStyles = source("src/styles/layouts.css");

    for (const selector of [
      ".panel",
      ".data-table",
      ".button-primary",
      ".button-secondary",
      ".button-danger",
      ".status-chip",
      ".page-state",
      ".form-control",
    ]) {
      expect(componentStyles, `${selector} should be centralized`).toContain(selector);
    }

    for (const selector of [
      ".application-shell",
      ".page-shell",
      ".page-heading",
      ".metric-grid",
    ]) {
      expect(layoutStyles, `${selector} should be centralized`).toContain(selector);
    }
  });

  it("keeps Chinese glyph support in technical labels and collapses empty structure tracks", () => {
    const tokens = source("src/styles/tokens.css");
    const components = source("src/styles/components.css");

    expect(tokens).toMatch(/--font-mono:[^;]*Noto Sans SC Variable[^;]*;/);
    expect(components).toContain("repeat(auto-fit, minmax(250px, 1fr))");
  });

  it("keeps simple administration page styles in the centralized layers", () => {
    for (const path of [
      "src/admin/AuditPage.vue",
      "src/admin/FilesPage.vue",
      "src/admin/JobsPage.vue",
      "src/admin/SystemPage.vue",
      "src/admin/UsersPage.vue",
    ]) {
      const pageSource = source(path);
      expect(pageSource, `${path} should not own shared table or control CSS`).not.toContain("<style scoped>");
    }
  });

  it("documents the remaining component-specific style exceptions", () => {
    expect(matchingVueLines(
      /\.(?:button-primary|button-secondary|button-danger|admin-panel|page-heading|page-state)\b|table\s*\{/,
    )).toEqual([
      "src/approvals/ScientificApprovalReview.vue:.binding-table { display: grid; gap: 8px; padding: 16px; border: 1px solid var(--line); background: var(--surface); }",
      "src/approvals/ScientificApprovalReview.vue:.binding-table table { width: 100%; border-collapse: collapse; font-size: .68rem; }",
    ]);

    expect(matchingVueLines(/#[0-9a-fA-F]{3,8}|rgba?\(/)).toEqual([
      "src/review/conflicts/ConflictResolver.vue:.conflict-layer { position: fixed; z-index: 90; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(23, 43, 60, .62); }",
      "src/review/conflicts/ConflictResolver.vue:.conflict-dialog { width: min(100%, 510px); padding: 28px; border-top: 4px solid var(--danger); box-shadow: 0 28px 80px rgba(23, 43, 60, .25); }",
    ]);
  });
});
