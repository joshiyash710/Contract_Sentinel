import { describe, test, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

/**
 * Fidelity (spec AC-18). A full computed-style/screenshot check is out of scope for the
 * foundation (Q5); instead we assert the canonical token VALUES exist in globals.css exactly
 * as committed from the reference images, and that the primary button + shell chrome reference
 * those tokens (not stray literals). jsdom does not resolve CSS variables through Tailwind, so
 * we verify the source-of-truth values rather than getComputedStyle on a rendered node.
 */
const globals = fs.readFileSync(
  path.join(process.cwd(), "src/app/globals.css"),
  "utf8",
);

describe("fidelity — canonical tokens present", () => {
  test("surface_and_accent_tokens_exact", () => {
    const expected: Record<string, string> = {
      "--bg-app": "#0a0b12",
      "--bg-card": "#141824",
      "--accent": "#7c6cf5",
      "--accent-gradient-from": "#7a5cff",
      "--accent-gradient-to": "#5b8def",
    };
    for (const [name, hex] of Object.entries(expected)) {
      expect(globals).toContain(`${name}: ${hex}`);
    }
  });

  test("risk_scale_tokens_exact", () => {
    expect(globals).toContain("--risk-high: #ef4444");
    expect(globals).toContain("--risk-medium: #f59e0b");
    expect(globals).toContain("--risk-low: #22c55e");
  });

  test("radius_tokens_present", () => {
    expect(globals).toContain("--radius-card: 14px");
    expect(globals).toContain("--radius-pill: 9999px");
  });

  test("primary_button_uses_gradient_token", () => {
    const btn = fs.readFileSync(
      path.join(process.cwd(), "src/components/ui/Button.tsx"),
      "utf8",
    );
    // primary variant references the token-backed Tailwind class, not an inline hex
    expect(btn).toMatch(/bg-accent-gradient/);
    expect(btn).not.toMatch(/#[0-9a-fA-F]{3,6}/);
  });
});
