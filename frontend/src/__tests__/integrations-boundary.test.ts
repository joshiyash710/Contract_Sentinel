import { describe, test, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/**
 * Boundary check (spec 024 AC-6): integrations components reach the backend ONLY through
 * getApiClient() / hooks (useCurrentUser) — no component imports a concrete provider directly.
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

describe("integrations seam boundary (AC-6)", () => {
  test("no direct provider imports in components/integrations", () => {
    for (const file of filesUnder(join(ROOT, "components", "integrations"))) {
      const src = readFileSync(file, "utf8");
      expect(src, `${file} must not import realProvider`).not.toMatch(/realProvider/);
      expect(src, `${file} must not import mockProvider`).not.toMatch(/mockProvider/);
    }
  });
});
