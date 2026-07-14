/**
 * Boundary test: no page/component in components/auth or components/marketing
 * imports a provider directly (013 seam rule / AC-19).
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "fs";
import { join } from "path";

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

const SRC = join(__dirname, "..", "components");
const BANNED_IMPORTS = ["realProvider", "mockProvider"];

describe("auth-boundary: no direct provider imports in marketing/auth components", () => {
  for (const dir of ["auth", "marketing"]) {
    const fullDir = join(SRC, dir);
    const files = readAllTs(fullDir);
    for (const file of files) {
      it(`${dir}/${file.split(dir + "/")[1]} has no banned provider imports`, () => {
        const src = readFileSync(file, "utf-8");
        for (const banned of BANNED_IMPORTS) {
          expect(src).not.toContain(banned);
        }
      });
    }
  }
});
