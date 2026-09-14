import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";


const frontendRoot = resolve(import.meta.dirname, "..");

function source(path: string): string {
  return readFileSync(resolve(frontendRoot, path), "utf8");
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
});
