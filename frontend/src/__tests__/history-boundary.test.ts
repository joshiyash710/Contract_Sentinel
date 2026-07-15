/**
 * Boundary test (021 AC-10): no component under components/history imports a provider directly —
 * the view reaches the backend only via getApiClient() (through useJobs). Modeled on
 * auth-boundary.test.ts (013 seam rule).
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "fs";
import { basename, join } from "path";

function readAllTs(dir: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      results.push(...readAllTs(full));
    } else if (full.endsWith(".tsx") || full.endsWith(".ts")) {
      results.push(full);
    }
  }
  return results;
}

const HISTORY_DIR = join(__dirname, "..", "components", "history");
const BANNED_IMPORTS = ["realProvider", "mockProvider"];

describe("history-boundary: no direct provider imports in components/history", () => {
  const files = readAllTs(HISTORY_DIR);
  for (const file of files) {
    it(`${basename(file)} has no banned provider imports`, () => {
      const src = readFileSync(file, "utf-8");
      for (const banned of BANNED_IMPORTS) {
        expect(src).not.toContain(banned);
      }
    });
  }
});
