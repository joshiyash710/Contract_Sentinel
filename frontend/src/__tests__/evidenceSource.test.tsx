import { describe, test, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import {
  EvidenceSourceBadge,
  evidenceSourceLabel,
} from "@/components/report/EvidenceSourceBadge";
import { FindingCard } from "@/components/report/FindingCard";
import { reportFixture } from "@/lib/api/fixtures";
import type { ReportFinding } from "@/lib/api/types";

/**
 * Feature 058 — evidence-source badge. Surfaces the already-present ReportFinding.path_taken
 * ("local_kb" / "web_fallback") as a source badge in the finding-card header (AC-1..AC-7, AC-5)
 * and as a secondary label on the expanded "Supporting sources" section (AC-10), without
 * regressing the existing confidence display (AC-6). Unknown/null path → render nothing (AC-3/AC-4).
 */

const byId = (id: string): ReportFinding => {
  const f = reportFixture.findings.find((x) => x.clause_id === id);
  if (!f) throw new Error(`fixture finding ${id} missing`);
  return f;
};

describe("EvidenceSourceBadge (unit) — AC-1..AC-4, AC-7", () => {
  test("local_kb renders 'Local knowledge base' (AC-1)", () => {
    render(<EvidenceSourceBadge path="local_kb" />);
    expect(screen.getByText("Local knowledge base")).toBeInTheDocument();
  });

  test("web_fallback renders 'Live web search' (AC-2)", () => {
    render(<EvidenceSourceBadge path="web_fallback" />);
    expect(screen.getByText("Live web search")).toBeInTheDocument();
  });

  test("null path renders no badge (AC-3)", () => {
    render(<EvidenceSourceBadge path={null} />);
    expect(screen.queryByTestId("evidence-source-badge")).not.toBeInTheDocument();
  });

  test("unknown/stale path values render no badge (AC-4)", () => {
    for (const p of ["corrective", "direct", ""]) {
      const { unmount } = render(<EvidenceSourceBadge path={p} />);
      expect(screen.queryByTestId("evidence-source-badge")).not.toBeInTheDocument();
      unmount();
    }
  });

  test("the two sources use distinct tones and no raw hex (AC-7)", () => {
    // The StatusBadge pill is the element carrying the label text; its className holds the tone classes.
    // The hex-regex guards the component SOURCE (Tailwind token classes only), not computed styles.
    const { unmount } = render(<EvidenceSourceBadge path="local_kb" />);
    const localCls = screen.getByText("Local knowledge base").className;
    unmount();
    render(<EvidenceSourceBadge path="web_fallback" />);
    const webCls = screen.getByText("Live web search").className;

    expect(localCls).not.toEqual(webCls);
    expect(localCls).not.toMatch(/#[0-9a-f]{3,6}/i);
    expect(webCls).not.toMatch(/#[0-9a-f]{3,6}/i);
  });
});

describe("evidenceSourceLabel (unit) — shared helper", () => {
  test("maps known values, null for null/unknown", () => {
    expect(evidenceSourceLabel("local_kb")).toBe("Local knowledge base");
    expect(evidenceSourceLabel("web_fallback")).toBe("Live web search");
    expect(evidenceSourceLabel(null)).toBeNull();
    expect(evidenceSourceLabel("corrective")).toBeNull();
    expect(evidenceSourceLabel(undefined)).toBeNull();
  });
});

describe("FindingCard integration — AC-5, AC-6, AC-10", () => {
  test("source badge is visible while the card is collapsed (AC-5)", () => {
    render(<FindingCard finding={byId("c-001")} />); // defaultOpen false
    expect(screen.getByTestId("evidence-source-badge")).toBeInTheDocument();
    expect(screen.getByText("Local knowledge base")).toBeInTheDocument();
  });

  test("confidence display is unchanged (AC-6)", () => {
    // c-001 has confidence_score 0.82 → "82% confidence".
    const { unmount } = render(<FindingCard finding={byId("c-001")} />);
    expect(screen.getByText(/82% confidence/i)).toBeInTheDocument();
    unmount();
    // c-003 has confidence_score null → no "% confidence" text.
    render(<FindingCard finding={byId("c-003")} />);
    expect(screen.queryByText(/% confidence/i)).not.toBeInTheDocument();
  });

  test("expanded evidence section carries the source label (AC-10)", () => {
    // c-001 (local_kb, has evidence) → header includes the local-KB source.
    const { unmount } = render(<FindingCard finding={byId("c-001")} defaultOpen />);
    expect(screen.getByText(/supporting sources.*local knowledge base/i)).toBeInTheDocument();
    unmount();

    // c-002 (web_fallback, has evidence) → header includes the web source.
    const r2 = render(<FindingCard finding={byId("c-002")} defaultOpen />);
    expect(screen.getByText(/supporting sources.*live web search/i)).toBeInTheDocument();
    r2.unmount();

    // c-003 (web_fallback but evidence []) → the section does not render at all → no label.
    const { container } = render(<FindingCard finding={byId("c-003")} defaultOpen />);
    expect(within(container).queryByText(/supporting sources/i)).not.toBeInTheDocument();
  });
});
