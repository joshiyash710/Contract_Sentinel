import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { RiskBadge } from "@/components/ui/RiskBadge";

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

describe("design tokens", () => {
  test("no_hardcoded_hex", () => {
    // Hex literals may appear ONLY in globals.css and src/lib/tokens.ts (spec AC-1).
    const dir = path.join(process.cwd(), "src/components");
    const offenders = walk(dir).filter((f) => /#[0-9a-fA-F]{3,6}\b/.test(fs.readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
  });

  test("risk_tokens_map_to_levels", () => {
    (["low", "medium", "high"] as const).forEach((level) => {
      const { unmount } = render(<RiskBadge level={level} />);
      const el = screen.getByTestId(`risk-badge-${level}`);
      expect(el.className).toMatch(new RegExp(`risk-${level}`));
      unmount();
    });
  });

  test("single_dark_theme", () => {
    const css = fs.readFileSync(path.join(process.cwd(), "src/app/globals.css"), "utf8");
    expect(css).not.toMatch(/\.light\b|prefers-color-scheme:\s*light|\[data-theme=.light.\]/);
  });
});
