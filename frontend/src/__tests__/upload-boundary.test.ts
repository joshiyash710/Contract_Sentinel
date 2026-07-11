import { describe, test, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

function readAll(dir: string): string[] {
  const out: string[] = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...readAll(p));
    else out.push(fs.readFileSync(p, "utf8"));
  }
  return out;
}

describe("015 boundary (spec AC-16)", () => {
  test("screens_use_getApiClient_only", () => {
    // No feature screen imports a concrete provider — only the getApiClient() seam.
    for (const sub of ["upload", "processing"]) {
      const dir = path.join(process.cwd(), "src/components", sub);
      readAll(dir).forEach((src) => {
        expect(src).not.toMatch(/mockProvider|realProvider/);
      });
    }
  });
});
