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
});
