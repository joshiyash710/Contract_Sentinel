import { describe, test, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/** Boundary check (spec 018 AC-18): dashboard views reach the backend only via
 * getApiClient() — no direct provider import. */
const DIR = join(__dirname, "..", "components", "dashboard");

describe("dashboard seam boundary (AC-18)", () => {
  test("no direct provider imports in dashboard components", () => {
    for (const name of readdirSync(DIR)) {
      if (!/\.tsx?$/.test(name)) continue;
      const src = readFileSync(join(DIR, name), "utf8");
      expect(src, `${name} must not import realProvider`).not.toMatch(/realProvider/);
      expect(src, `${name} must not import mockProvider`).not.toMatch(/mockProvider/);
    }
  });
});
