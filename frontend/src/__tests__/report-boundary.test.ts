import { describe, test, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/**
 * Boundary check (spec 017 AC-15): report components and the modified ProcessingView reach the
 * backend ONLY through getApiClient() — no component imports a concrete provider directly. This
 * keeps the mock↔real swap a single-flag change (013 seam). The no-backend-edits half of AC-15
 * is verified in Task 8 via `git diff`.
 */
const ROOT = join(__dirname, "..");

function filesUnder(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...filesUnder(full));
    else if (/\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

describe("report seam boundary (AC-15)", () => {
  test("no direct provider imports in report components or ProcessingView", () => {
    const targets = [
      ...filesUnder(join(ROOT, "components", "report")),
      join(ROOT, "components", "processing", "ProcessingView.tsx"),
    ];
    for (const file of targets) {
      const src = readFileSync(file, "utf8");
      expect(src, `${file} must not import realProvider`).not.toMatch(/realProvider/);
      expect(src, `${file} must not import mockProvider`).not.toMatch(/mockProvider/);
    }
  });
});
