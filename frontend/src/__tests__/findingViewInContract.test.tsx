import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FindingCard } from "@/components/report/FindingCard";
import { reportFixture } from "@/lib/api/fixtures";
import type { ReportFinding } from "@/lib/api/types";

// Feature 057 — the "View in contract" affordance on a finding (AC-2/AC-3).

const LOCATOR = { pages: [2], spans: [{ page: 2, bbox: [10, 20, 100, 60] }] };

function finding(overrides: Partial<ReportFinding> = {}): ReportFinding {
  return { ...reportFixture.findings[0], ...overrides };
}

describe("FindingCard view-in-contract (feature 057)", () => {
  test("shows the button and calls back on click when a locator + handler exist (AC-2/AC-3)", () => {
    const onView = vi.fn();
    const f = finding({ source_locator: LOCATOR });
    render(<FindingCard finding={f} defaultOpen onViewInContract={onView} />);

    const btn = screen.getByTestId("view-in-contract");
    fireEvent.click(btn);
    expect(onView).toHaveBeenCalledWith(f);
  });

  test("no button when the finding has no source_locator (AC-2)", () => {
    render(<FindingCard finding={finding({ source_locator: null })} defaultOpen onViewInContract={vi.fn()} />);
    expect(screen.queryByTestId("view-in-contract")).not.toBeInTheDocument();
  });

  test("no button when no handler is wired (017 standalone)", () => {
    render(<FindingCard finding={finding({ source_locator: LOCATOR })} defaultOpen />);
    expect(screen.queryByTestId("view-in-contract")).not.toBeInTheDocument();
  });
});
